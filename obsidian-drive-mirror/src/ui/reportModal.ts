import { App, Modal } from "obsidian";
import type { SyncReport } from "../mirror/state";

const fmtBytes = (n: number) => (n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KiB` : `${(n / 1024 / 1024).toFixed(1)} MiB`);

/** Diagnostics: content-free report of recent runs (usable on iOS without Web Inspector). */
export class ReportModal extends Modal {
  constructor(
    app: App,
    private readonly history: SyncReport[],
    private readonly lastCompleteSyncAt: string | null,
  ) {
    super(app);
  }

  override onOpen(): void {
    const { contentEl } = this;
    this.setTitle("Drive Mirror — diagnostics");
    contentEl.createEl("p", { text: `Last complete sync: ${this.lastCompleteSyncAt ?? "never"}` });
    contentEl.createEl("p", {
      cls: "setting-item-description",
      text: "A complete bridge snapshot means the PC's Drive folder was stable during two scans; it does not prove Drive for desktop had finished syncing with Google.",
    });
    if (this.history.length === 0) {
      contentEl.createEl("p", { text: "No runs yet." });
      return;
    }
    for (const r of this.history) {
      const d = contentEl.createEl("details");
      d.open = r === this.history[0];
      d.createEl("summary", { text: `${r.startedAt} — ${r.status}` });
      const c = r.counts;
      const a = r.applied;
      d.createEl("pre", {
        text: [
          `remote ${c.remote}  local ${c.local}  unchanged ${c.unchanged}`,
          `planned: create ${c.create}, replace ${c.replace} (local edits ${c.localEdits}), delete ${c.delete}, oversize ${c.skippedOversize}`,
          `applied: created ${a.created}, replaced ${a.replaced}, deleted ${a.deleted}, folders removed ${a.foldersRemoved}`,
          `excluded: remote ${c.excludedRemote}, local ${c.excludedLocal}`,
          `downloaded ${fmtBytes(r.bytesDownloaded)}, hashed locally ${fmtBytes(r.hashedLocalBytes)}`,
          `snapshot ${r.snapshotId ?? "-"}  finished ${r.finishedAt}`,
        ].join("\n"),
      });
      if (r.failures.length) {
        d.createEl("h6", { text: `Failures (${r.failures.length})` });
        const ul = d.createEl("ul");
        for (const f of r.failures.slice(0, 50)) ul.createEl("li", { text: `[${f.code}] ${f.path ?? ""} ${f.message}` });
      }
      if (r.warnings.length) {
        d.createEl("h6", { text: `Warnings (${r.warnings.length})` });
        const ul = d.createEl("ul");
        for (const w of r.warnings.slice(0, 50)) ul.createEl("li", { text: w });
      }
    }
  }

  override onClose(): void {
    this.contentEl.empty();
  }
}
