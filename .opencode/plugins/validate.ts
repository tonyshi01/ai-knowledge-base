import type { Plugin } from "@opencode-ai/plugin";

const TARGET_PATTERN = /^knowledge\/articles\/.*\.json$/;

function getFilePath(args: unknown): string | null {
  if (typeof args !== "object" || args === null) return null;
  const a = args as Record<string, unknown>;
  const path = a.file_path ?? a.filePath ?? null;
  return typeof path === "string" ? path : null;
}

function shouldValidate(tool: string, filePath: string): boolean {
  if (tool !== "write" && tool !== "edit") return false;
  return TARGET_PATTERN.test(filePath);
}

const plugin: Plugin = async (input) => ({
  "tool.execute.after": async (call) => {
    const filePath = getFilePath(call.args);
    if (!filePath || !shouldValidate(call.tool, filePath)) return;

    try {
      const result = await input
        .$`python3 hooks/validate_json.py ${input.$.escape(filePath)}`
        .nothrow();

      const decode = (buf: unknown) =>
        buf instanceof Uint8Array ? new TextDecoder().decode(buf) : "";

      const stdout = decode(result.stdout);
      const stderr = decode(result.stderr);

      if (result.exitCode !== 0) {
        console.warn(`[validate] ❌ ${filePath}\n${stdout}${stderr}`);
      } else {
        console.log(`[validate] ✅ ${filePath}`);
      }
    } catch (err) {
      console.error(`[validate] 异常: ${filePath}`, err);
    }
  },
});

export default plugin;
