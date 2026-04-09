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

@Service
public class RagService {

    private static final Logger log = LoggerFactory.getLogger(RagService.class);

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
        log.info("RAG query: {} (filter: {})", question, categoryFilter);

        var retrieverBuilder = VectorStoreDocumentRetriever.builder()
                .vectorStore(vectorStore)
                .similarityThreshold(0.3)
                .topK(5);

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
}
