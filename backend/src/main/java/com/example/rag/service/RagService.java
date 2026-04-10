package com.example.rag.service;

import com.example.rag.model.AskResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.rag.advisor.RetrievalAugmentationAdvisor;
import org.springframework.ai.rag.retrieval.search.VectorStoreDocumentRetriever;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.filter.FilterExpressionBuilder;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;

@Service
public class RagService {

    private static final Logger log = LoggerFactory.getLogger(RagService.class);

    private static final double DEFAULT_SIMILARITY_THRESHOLD = 0.3;
    private static final int DEFAULT_TOP_K = 5;

    private final ChatClient chatClient;
    private final VectorStore vectorStore;

    public RagService(ChatClient chatClient, VectorStore vectorStore) {
        this.chatClient = chatClient;
        this.vectorStore = vectorStore;
    }

    public AskResponse ask(String question) {
        return ask(question, null);
    }

    public AskResponse ask(String question, String categoryFilter) {
        return ask(question, categoryFilter, DEFAULT_SIMILARITY_THRESHOLD, DEFAULT_TOP_K);
    }

    public AskResponse ask(String question, String categoryFilter,
                           double similarityThreshold, int topK) {
        log.info("RAG query: {} (filter: {}, threshold: {}, topK: {})",
                question, categoryFilter, similarityThreshold, topK);

        var retrieverBuilder = VectorStoreDocumentRetriever.builder()
                .vectorStore(vectorStore)
                .similarityThreshold(similarityThreshold)
                .topK(topK);

        if (categoryFilter != null && !categoryFilter.isBlank()) {
            var filterBuilder = new FilterExpressionBuilder();
            retrieverBuilder.filterExpression(
                    filterBuilder.eq("incident.category", categoryFilter).build()
            );
        }

        var retriever = retrieverBuilder.build();

        RetrievalAugmentationAdvisor advisor = RetrievalAugmentationAdvisor.builder()
                .documentRetriever(retriever)
                .build();

        ChatResponse response = chatClient.prompt()
                .advisors(advisor)
                .user(question)
                .call()
                .chatResponse();

        String answer = response.getResult().getOutput().getText();

        List<String> sources = response.getMetadata().entrySet().stream()
                .filter(e -> e.getKey().contains("source"))
                .map(e -> e.getValue().toString())
                .distinct()
                .toList();

        return new AskResponse(answer, sources);
    }

    public AskResponse askSimple(String question) {
        log.info("Simple (non-RAG) query: {}", question);

        String answer = chatClient.prompt()
                .user(question)
                .call()
                .content();

        return new AskResponse(answer, List.of());
    }

    public String diagnose(String symptom, String kubectlOutput) {
        log.info("Diagnose: {}", symptom);

        var retriever = VectorStoreDocumentRetriever.builder()
                .vectorStore(vectorStore)
                .similarityThreshold(0.2)
                .topK(8)
                .build();

        RetrievalAugmentationAdvisor advisor = RetrievalAugmentationAdvisor.builder()
                .documentRetriever(retriever)
                .build();

        String prompt = "Diagnose the following Kubernetes issue:\n\n"
                + "Symptom: " + symptom + "\n";
        if (kubectlOutput != null && !kubectlOutput.isBlank()) {
            prompt += "\nkubectl output:\n```\n" + kubectlOutput + "\n```\n";
        }
        prompt += "\nProvide: 1) Root cause analysis 2) Suggested kubectl commands for further investigation 3) Recommended fix";

        return chatClient.prompt()
                .advisors(advisor)
                .user(prompt)
                .call()
                .content();
    }

    /**
     * Debug method: returns both the answer AND the retrieved documents.
     * Used by the evaluation framework to measure retrieval quality.
     */
    public Map<String, Object> askDebug(String question, String categoryFilter,
                                         double similarityThreshold, int topK) {
        log.info("Debug RAG query: {}", question);

        // First, retrieve documents directly
        var searchBuilder = SearchRequest.builder()
                .query(question)
                .similarityThreshold(similarityThreshold)
                .topK(topK);

        List<Document> retrievedDocs = vectorStore.similaritySearch(searchBuilder.build());

        // Build document summaries for the debug response
        List<Map<String, Object>> docSummaries = retrievedDocs.stream().map(doc -> {
            Map<String, Object> summary = new java.util.HashMap<>();
            summary.put("content", doc.getText().substring(0, Math.min(doc.getText().length(), 500)));
            summary.put("metadata", doc.getMetadata());
            return summary;
        }).collect(Collectors.toList());

        // Then get the full RAG answer
        AskResponse ragResponse = ask(question, categoryFilter, similarityThreshold, topK);

        return Map.of(
                "answer", ragResponse.answer(),
                "sources", ragResponse.sources(),
                "retrievedDocuments", docSummaries,
                "parameters", Map.of(
                        "similarityThreshold", similarityThreshold,
                        "topK", topK,
                        "categoryFilter", categoryFilter != null ? categoryFilter : ""
                )
        );
    }
}
