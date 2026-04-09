package com.example.rag.mcp;

import com.example.rag.model.AskResponse;
import com.example.rag.model.Interaction;
import com.example.rag.model.Session;
import com.example.rag.service.DocumentIngestionService;
import com.example.rag.service.RagService;
import com.example.rag.service.SessionService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * MCP Tool definitions for the RAG server.
 * These tools are exposed via Spring AI MCP Server and can be called
 * by OpenCode or any MCP-compatible client.
 */
@Component
public class RagMcpTools {

    private final RagService ragService;
    private final SessionService sessionService;
    private final DocumentIngestionService ingestionService;

    public RagMcpTools(RagService ragService, SessionService sessionService,
                       DocumentIngestionService ingestionService) {
        this.ragService = ragService;
        this.sessionService = sessionService;
        this.ingestionService = ingestionService;
    }

    @Tool(description = "Search the knowledge base for relevant information about Kubernetes issues, runbooks, and past incidents. " +
            "Returns contextual answers with source references.")
    public String ragQuery(
            @ToolParam(description = "The search query or question about K8s operations") String query,
            @ToolParam(description = "Optional category filter: OOMKill, CrashLoopBackOff, ResourceQuota, Network, ImagePull, NodePressure", required = false) String category
    ) {
        AskResponse response = ragService.ask(query, category);
        StringBuilder result = new StringBuilder();
        result.append(response.answer());
        if (!response.sources().isEmpty()) {
            result.append("\n\n---\nSources: ").append(String.join(", ", response.sources()));
        }
        return result.toString();
    }

    @Tool(description = "Diagnose a Kubernetes issue based on symptoms and optional kubectl output. " +
            "Uses RAG to find similar past incidents and provides structured diagnosis.")
    public String diagnose(
            @ToolParam(description = "Description of the symptom or issue") String symptom,
            @ToolParam(description = "Optional kubectl output for analysis", required = false) String kubectlOutput
    ) {
        return ragService.diagnose(symptom, kubectlOutput);
    }

    @Tool(description = "Start a new diagnostic session to track the troubleshooting process. " +
            "Returns a session ID for logging interactions.")
    public String sessionStart(
            @ToolParam(description = "Brief description of the issue being diagnosed") String description,
            @ToolParam(description = "K8s context/cluster name", required = false) String k8sContext
    ) {
        Session session = sessionService.startSession(description, k8sContext);
        return "Session started: " + session.getId() + "\nDescription: " + description;
    }

    @Tool(description = "Log an interaction in an active diagnostic session. " +
            "Use this to record commands executed, their output, and observations.")
    public String sessionLog(
            @ToolParam(description = "The session ID returned by session_start") String sessionId,
            @ToolParam(description = "Type: USER_QUERY, KUBECTL_COMMAND, KUBECTL_OUTPUT, LLM_RESPONSE, USER_ACTION") String type,
            @ToolParam(description = "The content of the interaction") String content
    ) {
        Interaction interaction = sessionService.logInteraction(sessionId, type, content, null);
        return "Logged [" + type + "] in session " + sessionId;
    }

    @Tool(description = "Resolve a diagnostic session. If outcome is RESOLVED, " +
            "the session transcript is automatically converted into a runbook entry for future reference.")
    public String sessionResolve(
            @ToolParam(description = "The session ID") String sessionId,
            @ToolParam(description = "Outcome: RESOLVED, UNRESOLVED, or ABANDONED") String outcome,
            @ToolParam(description = "Notes about the resolution or what was tried", required = false) String notes
    ) {
        Session session = sessionService.resolveSession(sessionId, outcome, notes);
        String msg = "Session " + sessionId + " resolved: " + outcome;
        if ("RESOLVED".equals(outcome)) {
            msg += "\nSession transcript has been ingested into the knowledge base for future reference.";
        }
        return msg;
    }

    @Tool(description = "Ingest raw text content into the knowledge base. " +
            "Useful for adding runbook entries, troubleshooting notes, or incident reports.")
    public String ingestContent(
            @ToolParam(description = "The text content to ingest") String content,
            @ToolParam(description = "A descriptive name for this content") String sourceName,
            @ToolParam(description = "Content type: runbook, incident-report, troubleshooting-guide", required = false) String contentType
    ) {
        Map<String, Object> metadata = Map.of(
                "source", sourceName,
                "type", contentType != null ? contentType : "manual-entry"
        );
        int chunks = ingestionService.ingestText(content, metadata);
        return "Ingested " + chunks + " chunks from '" + sourceName + "'";
    }
}
