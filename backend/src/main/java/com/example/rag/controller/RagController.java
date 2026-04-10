package com.example.rag.controller;

import com.example.rag.model.AskRequest;
import com.example.rag.model.AskResponse;
import com.example.rag.model.DocumentInfo;
import com.example.rag.model.IngestionResponse;
import com.example.rag.service.DocumentIngestionService;
import com.example.rag.service.FeedbackService;
import com.example.rag.service.RagService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class RagController {

    private final DocumentIngestionService ingestionService;
    private final RagService ragService;
    private final FeedbackService feedbackService;

    public RagController(DocumentIngestionService ingestionService, RagService ragService,
                        FeedbackService feedbackService) {
        this.ingestionService = ingestionService;
        this.ragService = ragService;
        this.feedbackService = feedbackService;
    }

    @PostMapping("/documents/upload")
    public ResponseEntity<IngestionResponse> uploadDocument(@RequestParam("file") MultipartFile file) {
        try {
            IngestionResponse response = ingestionService.ingest(file);
            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest()
                    .body(new IngestionResponse(file.getOriginalFilename(), 0, e.getMessage()));
        } catch (Exception e) {
            return ResponseEntity.internalServerError()
                    .body(new IngestionResponse(file.getOriginalFilename(), 0, "Error: " + e.getMessage()));
        }
    }

    @GetMapping("/documents")
    public ResponseEntity<List<DocumentInfo>> listDocuments() {
        return ResponseEntity.ok(ingestionService.getIngestedDocuments());
    }

    @PostMapping("/ask")
    public ResponseEntity<AskResponse> ask(@RequestBody AskRequest request) {
        try {
            AskResponse response = ragService.ask(request.question());
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            return ResponseEntity.ok(new AskResponse("Error: " + getRootCauseMessage(e), List.of()));
        }
    }

    @PostMapping("/ask/simple")
    public ResponseEntity<AskResponse> askSimple(@RequestBody AskRequest request) {
        try {
            AskResponse response = ragService.askSimple(request.question());
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            return ResponseEntity.ok(new AskResponse("Error: " + getRootCauseMessage(e), List.of()));
        }
    }

    @PostMapping("/api/diagnose")
    public ResponseEntity<Map<String, String>> diagnose(@RequestBody Map<String, String> request) {
        try {
            String diagnosis = ragService.diagnose(request.get("symptom"), request.get("kubectlOutput"));
            return ResponseEntity.ok(Map.of("diagnosis", diagnosis));
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("diagnosis", "Error: " + getRootCauseMessage(e)));
        }
    }

    /**
     * Parameterized RAG query for evaluation and parameter tuning.
     */
    @PostMapping("/ask/parameterized")
    public ResponseEntity<AskResponse> askParameterized(
            @RequestBody Map<String, Object> request) {
        try {
            String question = (String) request.get("question");
            String category = (String) request.get("category");
            double threshold = request.containsKey("similarityThreshold")
                    ? ((Number) request.get("similarityThreshold")).doubleValue() : 0.3;
            int topK = request.containsKey("topK")
                    ? ((Number) request.get("topK")).intValue() : 5;
            AskResponse response = ragService.ask(question, category, threshold, topK);
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            return ResponseEntity.ok(new AskResponse("Error: " + getRootCauseMessage(e), List.of()));
        }
    }

    /**
     * Debug endpoint for evaluation: returns answer + retrieved documents.
     */
    @PostMapping("/eval/ask-debug")
    public ResponseEntity<Map<String, Object>> askDebug(
            @RequestBody Map<String, Object> request) {
        try {
            String question = (String) request.get("question");
            String category = (String) request.get("category");
            double threshold = request.containsKey("similarityThreshold")
                    ? ((Number) request.get("similarityThreshold")).doubleValue() : 0.3;
            int topK = request.containsKey("topK")
                    ? ((Number) request.get("topK")).intValue() : 5;
            Map<String, Object> result = ragService.askDebug(question, category, threshold, topK);
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("error", getRootCauseMessage(e)));
        }
    }

    @PostMapping("/feedback/process")
    public ResponseEntity<Map<String, Object>> processFeedback() {
        int count = feedbackService.processUnprocessedSessions();
        return ResponseEntity.ok(Map.of("processed", count));
    }

    private String getRootCauseMessage(Throwable t) {
        while (t.getCause() != null) t = t.getCause();
        return t.getClass().getSimpleName() + ": " + t.getMessage();
    }
}
