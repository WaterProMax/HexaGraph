import { useState } from "react";
import type { BotInstance } from "../api/types";
import { AVATAR_EMOJI_CHOICES, AVATAR_PALETTE, readAvatarPresets, writeAvatarPreset, type BotAvatarPreset } from "../lib/botAvatar";
import { BotAvatar } from "./BotAvatar";

export type BotAvatarPickerProps = {
  bot: Pick<BotInstance, "bot_id" | "display_name" | "role_template" | "status">;
  onChanged?: (preset: BotAvatarPreset) => void;
  onClose?: () => void;
};

export function BotAvatarPicker({ bot, onChanged, onClose }: BotAvatarPickerProps) {
  const [preset, setPreset] = useState<BotAvatarPreset>(() => readAvatarPresets()[bot.bot_id] || {});

  const apply = (next: BotAvatarPreset) => {
    setPreset(next);
    writeAvatarPreset(bot.bot_id, next);
    onChanged?.(next);
  };

  return (
    <div className="surface bot-avatar-picker" data-testid="bot-avatar-picker" role="dialog" aria-label="更换头像">
      <div className="section-title">
        <span>更换头像</span>
        <button type="button" className="chip" onClick={onClose} aria-label="关闭头像选择器">
          关闭
        </button>
      </div>
      <div className="avatar-picker-preview">
        <BotAvatar bot={bot} size={56} preset={preset} />
        <span className="muted">默认头像由显示名与角色确定性生成；自定义只保存在本机浏览器。</span>
      </div>

      <div className="section-title" style={{ marginTop: 12 }}>
        <span>Emoji</span>
      </div>
      <div className="avatar-emoji-row">
        {AVATAR_EMOJI_CHOICES.map((emoji) => (
          <button
            key={emoji}
            type="button"
            className={`avatar-swatch ${preset.emoji === emoji ? "active" : ""}`}
            aria-label={`头像 ${emoji}`}
            data-emoji={emoji}
            onClick={() => apply({ ...preset, emoji })}
          >
            {emoji}
          </button>
        ))}
      </div>

      <div className="section-title" style={{ marginTop: 12 }}>
        <span>色板</span>
      </div>
      <div className="avatar-color-row">
        {AVATAR_PALETTE.map((color) => (
          <button
            key={color}
            type="button"
            className={`avatar-color ${preset.color === color ? "active" : ""}`}
            style={{ background: color }}
            aria-label={`颜色 ${color}`}
            data-color={color}
            onClick={() => apply({ ...preset, color })}
          />
        ))}
      </div>

      <div className="avatar-picker-actions">
        <button
          type="button"
          className="chip"
          onClick={() => apply({})}
          aria-label="恢复默认头像"
        >
          恢复默认
        </button>
      </div>
    </div>
  );
}

export default BotAvatarPicker;