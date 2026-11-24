/**
 * Per-project sidebar icon, persisted in localStorage like bot avatar presets.
 * Projects have no icon field on the backend yet; the server record stays the
 * authority for identity, this only stores a local presentation choice.
 */

export const PROJECT_ICON_STORAGE_KEY = "hexagraph.projectIcon.v1";
export const PROJECT_ICON_EVENT = "hexagraph:project-icon-changed";

export type ProjectIconPreset = {
  icon?: string;
  color?: string;
};

const HEX_COLOR = /^#[0-9a-f]{6}$/i;

function storageOrNull(storage?: Storage | null): Storage | null {
  if (storage) return storage;
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readProjectIcons(storage?: Storage | null): Record<string, ProjectIconPreset> {
  const target = storageOrNull(storage);
  if (!target) return {};
  try {
    const raw = target.getItem(PROJECT_ICON_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const clean: Record<string, ProjectIconPreset> = {};
    for (const [projectId, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!value || typeof value !== "object") continue;
      const record = value as Record<string, unknown>;
      const preset: ProjectIconPreset = {};
      if (typeof record.icon === "string" && record.icon.trim()) preset.icon = record.icon.trim().slice(0, 40);
      if (typeof record.color === "string" && HEX_COLOR.test(record.color)) preset.color = record.color;
      if (Object.keys(preset).length) clean[projectId] = preset;
    }
    return clean;
  } catch {
    return {};
  }
}

export function writeProjectIcon(
  projectId: string,
  preset: ProjectIconPreset,
  storage?: Storage | null,
): Record<string, ProjectIconPreset> {
  const target = storageOrNull(storage);
  const all = readProjectIcons(target);
  const clean: ProjectIconPreset = {};
  if (preset.icon && preset.icon.trim()) clean.icon = preset.icon.trim().slice(0, 40);
  if (preset.color && HEX_COLOR.test(preset.color)) clean.color = preset.color;
  if (Object.keys(clean).length) all[projectId] = clean;
  else delete all[projectId];
  try {
    target?.setItem(PROJECT_ICON_STORAGE_KEY, JSON.stringify(all));
  } catch {
    // Storage full or blocked: keep the default folder icon.
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(PROJECT_ICON_EVENT, { detail: { projectId } }));
  }
  return all;
}

export function clearProjectIcon(projectId: string, storage?: Storage | null): Record<string, ProjectIconPreset> {
  return writeProjectIcon(projectId, {}, storage);
}