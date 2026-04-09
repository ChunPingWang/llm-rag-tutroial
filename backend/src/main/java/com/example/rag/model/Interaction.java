package com.example.rag.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "interactions")
public class Interaction {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private String id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "session_id")
    private Session session;

    private String type; // USER_QUERY, KUBECTL_COMMAND, KUBECTL_OUTPUT, LLM_RESPONSE, USER_ACTION

    @Column(columnDefinition = "TEXT")
    private String content;

    @Column(columnDefinition = "TEXT")
    private String metadata; // JSON string for extra info (command exit code, k8s namespace, etc.)

    private LocalDateTime timestamp;

    public Interaction() {
        this.timestamp = LocalDateTime.now();
    }

    public Interaction(String type, String content) {
        this();
        this.type = type;
        this.content = content;
    }

    public Interaction(String type, String content, String metadata) {
        this(type, content);
        this.metadata = metadata;
    }

    // Getters and setters
    public String getId() { return id; }

    public Session getSession() { return session; }
    public void setSession(Session session) { this.session = session; }

    public String getType() { return type; }
    public void setType(String type) { this.type = type; }

    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }

    public String getMetadata() { return metadata; }
    public void setMetadata(String metadata) { this.metadata = metadata; }

    public LocalDateTime getTimestamp() { return timestamp; }
}
