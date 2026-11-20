export default function ProjectWorkstationPage({ projectId }: { projectId: string }) {
  return (
    <div className="page">
      <div className="page-head">
        <h1>项目工作台</h1>
        <p className="mono">{projectId}</p>
      </div>
    </div>
  );
}