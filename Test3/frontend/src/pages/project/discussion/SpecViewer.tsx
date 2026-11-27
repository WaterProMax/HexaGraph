import { useEffect } from "react";
import type { DiscussionSession } from "../../../api/types";
import { SpecDocument } from "./SpecDocument";

export type SpecViewerProps = {
  open: boolean;
  onClose: () => void;
  sessions: DiscussionSession[];
};

/**
 * Modal shell for the approved discussion spec. The document itself lives in
 * SpecDocument so the project task view can show the same read-only body inline.
 */
export function SpecViewer({ open, onClose, sessions }: SpecViewerProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="disc-dialog-mask"
      data-testid="disc-spec-mask"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="disc-dialog disc-spec-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="disc-spec-title"
        data-testid="disc-spec-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="disc-dialog-head">
          <h2 id="disc-spec-title">需求规格</h2>
          <button type="button" className="disc-dialog-close" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </header>
        <SpecDocument sessions={sessions} />
      </div>
    </div>
  );
}

export default SpecViewer;