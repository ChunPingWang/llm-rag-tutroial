package com.example.rag.service;

import com.example.rag.model.Interaction;
import com.example.rag.model.Session;
import com.example.rag.repository.SessionRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;

import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Converts resolved CLI sessions into RAG knowledge.
 * This is the core of the self-reinforcing feedback loop.
 */
@Service
public class FeedbackService {

    private static final Logger log = LoggerFactory.getLogger(FeedbackService.class);

    private final DocumentIngestionService ingestionService;
    private final ChatClient chatClient;
    private final SessionRepository sessionRepository;

    public FeedbackService(DocumentIngestionService ingestionService,
                          ChatClient chatClient,
                          SessionRepository sessionRepository) {
        this.ingestionService = ingestionService;
        this.chatClient = chatClient;
        this.sessionRepository = sessionRepository;
    }

    /**
     * Convert a resolved session into a RAG document for future retrieval.
     */
    public void ingestSessionFeedback(Session session) {
        if (session.isFeedbackIngested()) {
            log.debug("Session {} feedback already ingested, skipping", session.getId());
            return;
        }

        try {
            // Build the transcript
            String transcript = buildTranscript(session);

            // Use LLM to generate a structured runbook entry from the transcript
            String runbookEntry = generateRunbookEntry(transcript, session.getDescription());

            // Build metadata for filtered retrieval
            Map<String, Object> metadata = new HashMap<>();
            metadata.put("source", "session:" + session.getId());
            metadata.put("type", "cli-session-feedback");
            metadata.put("resolution.verified", "true");
            metadata.put("session.outcome", session.getOutcome());
            metadata.put("session.date", session.getStartedAt().format(DateTimeFormatter.ISO_LOCAL_DATE));

            // Detect incident category from transcript content
            detectCategoryFromTranscript(transcript, metadata);

            // Ingest into vector store
            int chunks = ingestionService.ingestText(runbookEntry, metadata);

            // Mark session as ingested
            session.setFeedbackIngested(true);
            sessionRepository.save(session);

            log.info("Feedback ingested for session {}: {} chunks created", session.getId(), chunks);
        } catch (Exception e) {
            log.error("Failed to ingest feedback for session {}: {}", session.getId(), e.getMessage(), e);
        }
    }

    /**
     * Process all unprocessed resolved sessions (batch job).
     */
    public int processUnprocessedSessions() {
        List<Session> sessions = sessionRepository.findByOutcomeAndFeedbackIngestedFalse("RESOLVED");
        int processed = 0;
        for (Session session : sessions) {
            ingestSessionFeedback(session);
            processed++;
        }
        log.info("Batch processed {} unprocessed sessions", processed);
        return processed;
    }

    private String buildTranscript(Session session) {
        StringBuilder sb = new StringBuilder();
        sb.append("# Diagnostic Session: ").append(session.getDescription()).append("\n\n");
        sb.append("Date: ").append(session.getStartedAt().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME)).append("\n");
        sb.append("K8s Context: ").append(session.getK8sContext()).append("\n");
        sb.append("Outcome: ").append(session.getOutcome()).append("\n\n");
        sb.append("## Interaction Log\n\n");

        for (Interaction interaction : session.getInteractions()) {
            sb.append("### ").append(interaction.getType()).append("\n");
            sb.append(interaction.getContent()).append("\n\n");
        }

        if (session.getNotes() != null) {
            sb.append("## Resolution Notes\n\n").append(session.getNotes()).append("\n");
        }

        return sb.toString();
    }

    private String generateRunbookEntry(String transcript, String description) {
        try {
            String prompt = """
                    Based on the following diagnostic session transcript, create a concise runbook entry
                    that can help diagnose similar issues in the future.

                    Format the output as:
                    ## Problem
                    [Brief description of the issue]

                    ## Symptoms
                    [Observable symptoms that indicate this issue]

                    ## Diagnosis Steps
                    [Numbered steps with specific kubectl commands]

                    ## Root Cause
                    [What caused the issue]

                    ## Resolution
                    [How the issue was resolved, with specific commands]

                    ## Prevention
                    [How to prevent this issue in the future]

                    Transcript:
                    """ + transcript;

            return chatClient.prompt()
                    .user(prompt)
                    .call()
                    .content();
        } catch (Exception e) {
            log.warn("Failed to generate runbook entry via LLM, using raw transcript: {}", e.getMessage());
            return transcript;
        }
    }

    private void detectCategoryFromTranscript(String transcript, Map<String, Object> metadata) {
        String lower = transcript.toLowerCase();
        if (lower.contains("oomkill") || lower.contains("out of memory") || lower.contains("oom")) {
            metadata.put("incident.category", "OOMKill");
        } else if (lower.contains("crashloopbackoff")) {
            metadata.put("incident.category", "CrashLoopBackOff");
        } else if (lower.contains("pending") && lower.contains("insufficient")) {
            metadata.put("incident.category", "ResourceQuota");
        } else if (lower.contains("imagepullbackoff") || lower.contains("errimagepull")) {
            metadata.put("incident.category", "ImagePull");
        } else if (lower.contains("networkpolicy") || lower.contains("connection refused") || lower.contains("timeout")) {
            metadata.put("incident.category", "Network");
        } else if (lower.contains("evicted") || lower.contains("disk pressure")) {
            metadata.put("incident.category", "NodePressure");
        }
    }
}
