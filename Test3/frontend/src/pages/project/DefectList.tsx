import type { DefectRecord } from "../../api/types";

export type DefectListProps = { defects: DefectRecord[]; onLocateTask: (taskCode: string) => void };

export function DefectList({ defects, onLocateTask }: DefectListProps) {
  return (
    <div className="surface defect-list" data-testid="defect-list" style={{ padding: 16 }}>
      <div className="section-title">
        <span>缺陷</span>
        <span className="hint mono">{defects.length}</span>
      </div>
      {defects.length === 0 ? (
        <p className="muted">没有未关闭的缺陷。</p>
      ) : (
        <ul className="defect-items">
          {defects.map((defect) => (
            <li key={defect.defect_id}>
              <button
                type="button"
                className="chip defect-item"
                data-testid={`defect-${defect.task_code}`}
                onClick={() => onLocateTask(defect.task_code)}
                title="定位到任务"
              >
                <span className="mono defect-code">{defect.task_code}</span>
                <span className="defect-detail">{defect.detail}</span>
                <span className="defect-evidence" title={defect.evidence_uris.join("\n")}>
                  证据 {defect.evidence_uris.length}
                </span>
                <span className={`chip status-${defect.status}`}>{defect.status}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default DefectList;