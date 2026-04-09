package com.example.rag.service;

import com.example.rag.model.Interaction;
import com.example.rag.model.Session;
import com.example.rag.repository.SessionRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class SessionService {

    private static final Logger log = LoggerFactory.getLogger(SessionService.class);

    private final SessionRepository sessionRepository;
    private final FeedbackService feedbackService;

    public SessionService(SessionRepository sessionRepository, FeedbackService feedbackService) {
        this.sessionRepository = sessionRepository;
        this.feedbackService = feedbackService;
    }

    @Transactional
    public Session startSession(String description, String k8sContext) {
        Session session = new Session(description, k8sContext);
        session = sessionRepository.save(session);
        log.info("Started diagnostic session: {} - {}", session.getId(), description);
        return session;
    }

    @Transactional
    public Interaction logInteraction(String sessionId, String type, String content, String metadata) {
        Session session = sessionRepository.findById(sessionId)
                .orElseThrow(() -> new IllegalArgumentException("Session not found: " + sessionId));

        Interaction interaction = new Interaction(type, content, metadata);
        session.addInteraction(interaction);
        sessionRepository.save(session);

        log.debug("Logged interaction [{}] in session {}: {}", type, sessionId,
                content.length() > 100 ? content.substring(0, 100) + "..." : content);
        return interaction;
    }

    @Transactional
    public Session resolveSession(String sessionId, String outcome, String notes) {
        Session session = sessionRepository.findById(sessionId)
                .orElseThrow(() -> new IllegalArgumentException("Session not found: " + sessionId));

        session.setOutcome(outcome);
        session.setNotes(notes);
        session.setResolvedAt(LocalDateTime.now());
        session = sessionRepository.save(session);

        log.info("Session {} resolved with outcome: {}", sessionId, outcome);

        // Trigger feedback ingestion for resolved sessions
        if ("RESOLVED".equals(outcome)) {
            feedbackService.ingestSessionFeedback(session);
        }

        return session;
    }

    public Session getSession(String sessionId) {
        return sessionRepository.findById(sessionId)
                .orElseThrow(() -> new IllegalArgumentException("Session not found: " + sessionId));
    }

    public List<Session> getResolvedSessions() {
        return sessionRepository.findByOutcome("RESOLVED");
    }
}
