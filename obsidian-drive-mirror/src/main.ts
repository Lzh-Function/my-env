import { Notice, Platform, Plugin } from "obsidian";
import { AdapterFs, AdapterStateStore, obsidianHttp } from "./obsidianFs";
import { MirrorEngine } from "./mirror/engine";
import type { Plan } from "./mirror/planner";
import type { MirrorState, SyncReport } from "./mirror/state";
import { BridgeProvider } from "./provider/bridge";
import { demoMockProvider, type MockProvider } from "./provider/mock";
import type { RemoteReadProvider } from "./provider/types";
import { DEFAULT_SETTINGS, engineSettings, TOKEN_SECRET_ID, type DriveMirrorSettings } from "./settings";
import { PreviewModal } from "./ui/previewModal";
import { ReportModal } from "./ui/reportModal";
import { DriveMirrorSettingTab } from "./ui/settingsTab";

export default class DriveMirrorPlugin extends Plugin {
  override settings: DriveMirrorSettings = { ...DEFAULT_SETTINGS };
  state: MirrorState | null = null;
  private store!: AdapterStateStore;
  private engine: MirrorEngine | null = null;
  private abort: AbortController | null = null;
  private statusEl: HTMLElement | null = null;
  private mock: MockProvider | null = null;

  private get internalDir(): string {
    return this.manifest.dir ?? `${this.app.vault.configDir}/plugins/${this.manifest.id}`;
  }

  override async onload(): Promise<void> {
    this.settings = { ...DEFAULT_SETTINGS, ...((await this.loadData()) as Partial<DriveMirrorSettings> | null) };
    this.store = new AdapterStateStore(this.app.vault.adapter, `${this.internalDir}/state.json`);
    this.state = await this.store.load().catch(() => null);

    if (!Platform.isMobile) this.statusEl = this.addStatusBarItem();
    this.setStatus(this.state?.history[0]?.status ?? "idle");

    this.addRibbonIcon("refresh-cw", "Drive Mirror: sync now", () => this.runSync(false));
    this.addCommand({ id: "sync-now", name: "Sync now", callback: () => this.runSync(false) });
    this.addCommand({ id: "dry-run", name: "Dry run (preview only)", callback: () => this.runSync(true) });
    this.addCommand({ id: "cancel", name: "Cancel running sync", callback: () => this.abort?.abort() });
    this.addCommand({ id: "diagnostics", name: "Show diagnostics", callback: () => this.showReport() });
    this.addSettingTab(new DriveMirrorSettingTab(this.app, this));
  }

  override onunload(): void {
    this.abort?.abort();
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  async forgetCredentials(): Promise<void> {
    await this.buildProvider().signOut().catch(() => undefined);
    this.setToken("");
    new Notice("Bridge token removed from this device.");
  }

  buildProvider(): RemoteReadProvider {
    if (this.settings.provider === "mock") return (this.mock ??= demoMockProvider());
    return new BridgeProvider(obsidianHttp, { baseUrl: this.settings.bridgeUrl, token: this.getToken() });
  }

  getToken(): string {
    return this.app.secretStorage.getSecret(TOKEN_SECRET_ID) ?? "";
  }

  setToken(token: string): void {
    this.app.secretStorage.setSecret(TOKEN_SECRET_ID, token);
  }

  async repinRoot(): Promise<void> {
    try {
      const root = await this.buildProvider().verifyRoot();
      const state = (await this.store.load()) ?? null;
      if (!state) return;
      if (!window.confirm(`Pin this vault to bridge root "${root.name}" (${root.rootId})? The next sync will make the vault match it.`)) return;
      state.rootIdentity = root;
      await this.store.save(state);
      this.state = state;
      new Notice("Root re-pinned. Run a dry run before syncing.");
    } catch (e) {
      new Notice(`Bridge error: ${(e as Error).message}`);
    }
  }

  showReport(): void {
    new ReportModal(this.app, this.state?.history ?? [], this.state?.lastCompleteSyncAt ?? null).open();
  }

  async runSync(dryRun: boolean): Promise<void> {
    if (this.engine?.isRunning) {
      new Notice("Drive Mirror: a sync is already running.");
      return;
    }
    let provider: RemoteReadProvider;
    try {
      provider = this.buildProvider();
    } catch (e) {
      new Notice(`Drive Mirror: ${(e as Error).message}`);
      return;
    }
    this.abort = new AbortController();
    this.engine = new MirrorEngine({
      fs: new AdapterFs(this.app.vault.adapter),
      provider,
      store: this.store,
      configDir: this.app.vault.configDir,
      internalDir: this.internalDir,
      settings: engineSettings(this.settings),
      onProgress: (p) => this.setStatus(p.total ? `${p.phase} ${p.done}/${p.total}` : p.phase),
    });
    const approve = (plan: Plan) =>
      plan.confirmations.length === 0 && !this.settings.confirmBeforeApply
        ? Promise.resolve(true)
        : new Promise<boolean>((resolve) => new PreviewModal(this.app, plan, resolve).open());

    try {
      const { report, plan } = await this.engine.run({ dryRun, signal: this.abort.signal, approve });
      this.state = await this.store.load();
      if (dryRun && plan) new PreviewModal(this.app, plan, () => undefined, true).open();
      this.notify(report);
    } catch (e) {
      new Notice(`Drive Mirror failed: ${(e as Error).message}`);
    } finally {
      this.abort = null;
    }
  }

  private notify(r: SyncReport): void {
    this.setStatus(r.status);
    if (r.status === "DRY_RUN") return;
    const a = r.applied;
    const head = `Drive Mirror: ${r.status}`;
    const body =
      r.status === "SUCCESS" || r.status === "PARTIAL"
        ? `+${a.created} ~${a.replaced} -${a.deleted}${r.counts.skippedOversize ? `, ${r.counts.skippedOversize} oversize skipped` : ""}`
        : (r.failures[0]?.message ?? "");
    new Notice(`${head}\n${body}`, r.status === "SUCCESS" ? 5000 : 10000);
  }

  private setStatus(text: string): void {
    this.statusEl?.setText(`Drive Mirror: ${text}`);
  }
}
