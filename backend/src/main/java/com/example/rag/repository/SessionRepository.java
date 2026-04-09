package com.example.rag.repository;

import com.example.rag.model.Session;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface SessionRepository extends JpaRepository<Session, String> {
    List<Session> findByOutcomeAndFeedbackIngestedFalse(String outcome);
    List<Session> findByOutcome(String outcome);
}
