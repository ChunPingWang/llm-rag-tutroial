package com.example.rag.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "diagnostic_sessions")
public class Session {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private String id;

    private String description;
    private String k8sContext;
    private String outcome; // RESOLVED, UNRESOLVED, ABANDONED

    @Column(columnDefinition = "TEXT")
    private String notes;

    private LocalDateTime startedAt;
    private LocalDateTime resolvedAt;

    @OneToMany(mappedBy = "session", cascade = CascadeType.ALL, orphanRemoval = true)
    @OrderBy("timestamp ASC")
    private List<Interaction> interactions = new ArrayList<>();

    private boolean feedbackIngested = false;

    public Session() {
        this.startedAt = LocalDateTime.now();
    }

    public Session(String description, String k8sContext) {
        this();
        this.description = description;
        this.k8sContext = k8sContext;
    }

    // Getters and setters
    public String getId() { return id; }

    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }

    public String getK8sContext() { return k8sContext; }
    public void setK8sContext(String k8sContext) { this.k8sContext = k8sContext; }

    public String getOutcome() { return outcome; }
    public void setOutcome(String outcome) { this.outcome = outcome; }

    public String getNotes() { return notes; }
    public void setNotes(String notes) { this.notes = notes; }

    public LocalDateTime getStartedAt() { return startedAt; }

    public LocalDateTime getResolvedAt() { return resolvedAt; }
    public void setResolvedAt(LocalDateTime resolvedAt) { this.resolvedAt = resolvedAt; }

    public List<Interaction> getInteractions() { return interactions; }

    public boolean isFeedbackIngested() { return feedbackIngested; }
    public void setFeedbackIngested(boolean feedbackIngested) { this.feedbackIngested = feedbackIngested; }

    public void addInteraction(Interaction interaction) {
        interactions.add(interaction);
        interaction.setSession(this);
    }
}
