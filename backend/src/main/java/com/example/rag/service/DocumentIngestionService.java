package com.example.rag.service;

import com.example.rag.model.DocumentInfo;
import com.example.rag.model.IngestionResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.document.Document;
import org.springframework.ai.reader.TextReader;
import org.springframework.ai.reader.pdf.PagePdfDocumentReader;
import org.springframework.ai.transformer.splitter.TokenTextSplitter;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.core.io.FileSystemResource;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;

@Service
public class DocumentIngestionService {

    private static final Logger log = LoggerFactory.getLogger(DocumentIngestionService.class);

    private final VectorStore vectorStore;
    private final List<DocumentInfo> ingestedDocuments = new CopyOnWriteArrayList<>();

    public DocumentIngestionService(VectorStore vectorStore) {
        this.vectorStore = vectorStore;
    }

    public IngestionResponse ingest(MultipartFile file) throws IOException {
        String filename = file.getOriginalFilename();
        if (filename == null) {
            throw new IllegalArgumentException("Filename is required");
        }

        String lowerName = filename.toLowerCase();
        List<Document> documents;

        if (lowerName.endsWith(".pdf")) {
            documents = readPdf(file);
        } else if (lowerName.endsWith(".txt") || lowerName.endsWith(".md")) {
            documents = readText(file);
        } else if (lowerName.endsWith(".yaml") || lowerName.endsWith(".yml")) {
            documents = readYaml(file);
        } else {
            throw new IllegalArgumentException("Unsupported file type. Supported: PDF, TXT, MD, YAML");
        }

        TokenTextSplitter splitter = new TokenTextSplitter();
        List<Document> chunks = splitter.apply(documents);

        for (Document chunk : chunks) {
            chunk.getMetadata().put("source", filename);
            detectK8sMetadata(chunk);
        }

        log.info("Ingesting {} chunks from '{}'", chunks.size(), filename);
        vectorStore.write(chunks);

        String type = lowerName.endsWith(".pdf") ? "PDF"
                : (lowerName.endsWith(".yaml") || lowerName.endsWith(".yml")) ? "YAML" : "TEXT";
        ingestedDocuments.add(new DocumentInfo(filename, type, chunks.size(), "INGESTED"));

        return new IngestionResponse(filename, chunks.size(),
                "Successfully ingested " + chunks.size() + " chunks from " + filename);
    }

    /**
     * Ingest raw text content directly (used by FeedbackService for CLI transcripts).
     */
    public int ingestText(String content, Map<String, Object> metadata) {
        Document doc = new Document(content, metadata);
        TokenTextSplitter splitter = new TokenTextSplitter();
        List<Document> chunks = splitter.apply(List.of(doc));

        for (Document chunk : chunks) {
            chunk.getMetadata().putAll(metadata);
        }

        vectorStore.write(chunks);
        log.info("Ingested {} chunks from direct text (source: {})", chunks.size(), metadata.get("source"));
        return chunks.size();
    }

    public List<DocumentInfo> getIngestedDocuments() {
        return new ArrayList<>(ingestedDocuments);
    }

    private void detectK8sMetadata(Document chunk) {
        String text = chunk.getText().toLowerCase();
        if (text.contains("kind: pod") || text.contains("pods")) {
            chunk.getMetadata().put("k8s.resource.kind", "Pod");
        } else if (text.contains("kind: deployment") || text.contains("deployments")) {
            chunk.getMetadata().put("k8s.resource.kind", "Deployment");
        } else if (text.contains("kind: service") || text.contains("services")) {
            chunk.getMetadata().put("k8s.resource.kind", "Service");
        }

        if (text.contains("oomkill") || text.contains("oom")) {
            chunk.getMetadata().put("incident.category", "OOMKill");
        } else if (text.contains("crashloopbackoff")) {
            chunk.getMetadata().put("incident.category", "CrashLoopBackOff");
        } else if (text.contains("pending") && text.contains("insufficient")) {
            chunk.getMetadata().put("incident.category", "ResourceQuota");
        } else if (text.contains("networkpolicy") || text.contains("network")) {
            chunk.getMetadata().put("incident.category", "Network");
        }
    }

    private List<Document> readPdf(MultipartFile file) throws IOException {
        Path tempFile = Files.createTempFile("rag-upload-", ".pdf");
        file.transferTo(tempFile.toFile());
        try {
            FileSystemResource resource = new FileSystemResource(tempFile.toFile());
            PagePdfDocumentReader reader = new PagePdfDocumentReader(resource);
            return reader.read();
        } finally {
            Files.deleteIfExists(tempFile);
        }
    }

    private List<Document> readText(MultipartFile file) throws IOException {
        Path tempFile = Files.createTempFile("rag-upload-", ".txt");
        file.transferTo(tempFile.toFile());
        try {
            FileSystemResource resource = new FileSystemResource(tempFile.toFile());
            TextReader reader = new TextReader(resource);
            reader.getCustomMetadata().putAll(Map.of("source", file.getOriginalFilename()));
            return reader.read();
        } finally {
            Files.deleteIfExists(tempFile);
        }
    }

    private List<Document> readYaml(MultipartFile file) throws IOException {
        Path tempFile = Files.createTempFile("rag-upload-", ".yaml");
        file.transferTo(tempFile.toFile());
        try {
            FileSystemResource resource = new FileSystemResource(tempFile.toFile());
            TextReader reader = new TextReader(resource);
            reader.getCustomMetadata().putAll(Map.of(
                    "source", file.getOriginalFilename(),
                    "type", "k8s-manifest"
            ));
            return reader.read();
        } finally {
            Files.deleteIfExists(tempFile);
        }
    }
}
