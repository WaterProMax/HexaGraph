export type ApprovalBannerProps = {
  round?: number;
  onOpen: () => void;
};

export function ApprovalBanner({ round, onOpen }: ApprovalBannerProps) {
  return (
    <section
      className="disc-approval-banner"
      data-testid="disc-approval-banner"
      aria-label="需求规格审批"
    >
      <div className="disc-approval-banner-text">
        <span className="disc-approval-banner-title">需求规格待你审批</span>
        {typeof round === "number" && (
          <span className="disc-approval-banner-round">第 {round} 轮</span>
        )}
      </div>
      <button type="button" className="disc-button-primary" onClick={onOpen}>
        查看并审批
      </button>
    </section>
  );
}

export default ApprovalBanner;