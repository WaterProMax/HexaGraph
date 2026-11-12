import type { ThemeConfig } from "antd";

export const FONT_SANS =
  '"Funnel Sans", -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';
export const FONT_MONO = '"Geist Mono", ui-monospace, "SF Mono", Menlo, monospace';

export const theme: ThemeConfig = {
  token: {
    colorPrimary: "#0066fa",
    colorInfo: "#0066fa",
    colorSuccess: "#12a150",
    colorWarning: "#f76808",
    colorError: "#e40014",
    colorText: "#18181b",
    colorTextSecondary: "#5d5d66",
    colorTextTertiary: "#6b6b73",
    colorBorder: "rgba(0,0,0,0.14)",
    colorBorderSecondary: "rgba(0,0,0,0.07)",
    colorBgLayout: "#ffffff",
    colorFillTertiary: "rgba(0,0,0,0.035)",
    colorFillSecondary: "rgba(0,0,0,0.055)",
    fontFamily: FONT_SANS,
    fontFamilyCode: FONT_MONO,
    fontSize: 13,
    borderRadius: 10,
    borderRadiusSM: 8,
    borderRadiusLG: 14,
    controlHeight: 32,
    controlHeightSM: 26,
    boxShadow: "0 0 0 1px #0000000f, 0 8px 24px -6px #00000024, 0 2px 6px -2px #0000000f",
    boxShadowSecondary: "0 0 0 1px #0000000f, 0 8px 24px -6px #00000024, 0 2px 6px -2px #0000000f",
  },
  components: {
    Button: {
      defaultShadow: "none",
      primaryShadow: "0 1px 2px rgba(0,102,250,0.25)",
      dangerShadow: "none",
      fontWeight: 500,
      paddingInlineSM: 10,
    },
    Input: { activeShadow: "0 0 0 3px rgba(0,102,250,0.14)" },
    Select: { optionSelectedBg: "rgba(0,0,0,0.05)" },
    Tag: { defaultBg: "rgba(0,0,0,0.04)" },
    Card: { headerFontSize: 13 },
    Table: { headerBg: "#fafafa", headerSplitColor: "transparent" },
    Message: { contentPadding: "8px 14px" },
  },
};
