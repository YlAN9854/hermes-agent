import { useNavigate } from "react-router-dom";
import { useProfileScope } from "@/contexts/useProfileScope";
import { ConversationPanel } from "./context-vis/ConversationPanel";
import { PageChrome } from "./context-vis/PageChrome";
import { SpineWorkspace } from "./context-vis/SpineWorkspace";
import { useContextVisController } from "./context-vis/useContextVisController";
import "@/context-vis-theme.css";

export default function ContextVisPage() {
  const { profile } = useProfileScope();
  const navigate = useNavigate();
  const controller = useContextVisController(profile);

  return (
    <div
      className="flex h-full flex-col"
      data-contextvis-shell
      style={{ background: "var(--cv-bg)", color: "var(--cv-text)" }}
    >
      <PageChrome
        detail={controller.detail}
        error={controller.error}
        loading={controller.loading}
        notice={controller.notice}
        onClose={() => navigate("/")}
        onDismissError={() => controller.setError(null)}
        onDismissNotice={() => controller.setNotice(null)}
        onRefreshSurvival={() => void controller.runJob({ action: "refresh_survival" })}
        onSelect={controller.setSelected}
        selected={controller.selected}
        sessions={controller.sessions}
        working={controller.working}
      />
      <div className="cv-page-body flex min-h-0 flex-1">
        <ConversationPanel
          activeSpans={controller.activeSpans}
          activeUnitTurns={controller.activeUnitTurns}
          detail={controller.detail}
          mode={controller.conversationMode}
          onModeChange={controller.setConversationMode}
          onOpenLive={() => {
            if (controller.selected) {
              navigate(`/chat?resume=${encodeURIComponent(controller.selected)}`);
            }
          }}
          onSelectTurn={controller.selectTurn}
          selected={controller.selected}
        />
        <section
          aria-label="Semantic spine"
          className="flex min-h-0 min-w-0 flex-1 flex-col"
          style={{ background: "var(--cv-bg)" }}
        >
          <SpineWorkspace
            activeUnit={controller.activeUnit}
            detail={controller.detail}
            onCaptureHandler={controller.registerCapture}
            onDetailChange={controller.setDetail}
            onHoverSpans={controller.setActiveSpans}
            onLocate={controller.locateSpan}
            onRunJob={(body) => void controller.runJob(body)}
            onSaveEdits={controller.saveEdits}
            onSaveIntent={controller.saveIntent}
            onSelectUnit={controller.selectUnit}
            onTogglePin={(unit) => void controller.togglePin(unit)}
            working={controller.working}
          />
        </section>
      </div>
    </div>
  );
}
