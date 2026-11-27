import { useEffect, useState } from "react";
import { FolderOpenOutlined } from "@ant-design/icons";
import { PROJECT_ICON_EVENT, readProjectIcons } from "../lib/projectIcon";
import { SidebarGlyph } from "./sidebarIcons";

export function ProjectIcon({ projectId, size = 22 }: { projectId: string; size?: number }) {
  const [, setVersion] = useState(0);
  useEffect(() => {
    const onChange = () => setVersion((value) => value + 1);
    window.addEventListener(PROJECT_ICON_EVENT, onChange);
    return () => window.removeEventListener(PROJECT_ICON_EVENT, onChange);
  }, []);

  const preset = readProjectIcons()[projectId];
  if (!preset?.icon && !preset?.color) return <FolderOpenOutlined />;

  return (
    <span
      className="project-icon-tile"
      style={{ width: size, height: size, background: preset.color || "#2f80ed" }}
      aria-hidden
    >
      {preset.icon ? (
        <SidebarGlyph name={preset.icon} size={Math.round(size * 0.58)} />
      ) : (
        <FolderOpenOutlined style={{ fontSize: Math.round(size * 0.54) }} />
      )}
    </span>
  );
}

export default ProjectIcon;