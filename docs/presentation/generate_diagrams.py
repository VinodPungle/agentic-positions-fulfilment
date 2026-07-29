"""Generates architecture-overview.png and architecture-detailed.png in this folder.

Run from this directory: `python generate_diagrams.py` (requires matplotlib —
`pip install matplotlib`). Re-run after editing the box/arrow definitions below
to regenerate the PNGs used in README.md; there is no separate "build" step.

Palette matches docs/account-staffing-briefing.html: ink #12161D, accent blue #0B5FFF.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib.patches import FancyArrowPatch

INK = "#12161D"
INK_SOFT = "#57626F"
LINE = "#DEE2E8"
BLUE = "#0B5FFF"
BLUE_FILL = "#E8F0FF"
GREEN = "#1B8F52"
GREEN_FILL = "#E7F5EC"
PURPLE = "#7A3FE0"
PURPLE_FILL = "#F1EAFE"
AMBER = "#A6720A"
AMBER_FILL = "#FBF1DC"
GRAY_FILL = "#F5F6F8"
GRAY = "#8992A0"
WHITE = "#FFFFFF"


def draw_box(ax, x, y, w, h, title, subtitle=None, fill=BLUE_FILL, edge=BLUE, title_size=11.5, sub_size=9, title_color=None, z=3):
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
                          linewidth=1.4, edgecolor=edge, facecolor=fill, zorder=z)
    ax.add_patch(box)
    tc = title_color or INK
    if subtitle:
        ax.text(x + w / 2, y + h * 0.62, title, ha="center", va="center", fontsize=title_size,
                 fontweight="bold", color=tc, zorder=z + 1, family="DejaVu Sans")
        ax.text(x + w / 2, y + h * 0.28, subtitle, ha="center", va="center", fontsize=sub_size,
                 color=INK_SOFT, zorder=z + 1, family="DejaVu Sans", wrap=True)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center", fontsize=title_size,
                 fontweight="bold", color=tc, zorder=z + 1, family="DejaVu Sans")


def draw_group_label(ax, x, y, text, color=INK_SOFT):
    ax.text(x, y, text, fontsize=9.5, fontweight="bold", color=color, family="DejaVu Sans",
            ha="left", va="center", zorder=4,
            bbox=dict(boxstyle="round,pad=0.28", facecolor=WHITE, edgecolor="none"))


def draw_arrow(ax, p1, p2, color=GRAY, style="-", lw=1.6, label=None, label_size=8.3, curve=0.0, dashed=False):
    connectionstyle = f"arc3,rad={curve}"
    ls = (0, (4, 3)) if dashed else "solid"
    arrow = FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=14, linewidth=lw,
                             color=color, connectionstyle=connectionstyle, linestyle=ls, zorder=2)
    ax.add_patch(arrow)
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(mx, my + 0.12, label, ha="center", va="bottom", fontsize=label_size,
                 color=INK_SOFT, family="DejaVu Sans", zorder=5,
                 bbox=dict(boxstyle="round,pad=0.15", facecolor=WHITE, edgecolor="none", alpha=0.9))


def new_fig(w=14, h=7.9):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    return fig, ax


# ============================================================
# DIAGRAM 1 — Technical Architecture (overview)
# ============================================================
fig, ax = new_fig(14, 7.9)

ax.text(0.4, 7.68, "Technical Architecture — Agentic Fulfilment Prototype", fontsize=17,
        fontweight="bold", color=INK, family="DejaVu Sans", ha="left")
ax.text(0.4, 7.35, "Single containerized FastAPI service, MongoDB Atlas, OpenAI GPT-4o, hosted on Azure Container Apps",
        fontsize=10.5, color=INK_SOFT, family="DejaVu Sans", ha="left")

# Client tier
draw_box(ax, 0.6, 5.9, 3.1, 0.95, "User's Browser", "React 19 SPA (Tailwind + shadcn/ui)", fill=GRAY_FILL, edge=GRAY)

# App tier — central
draw_box(ax, 4.7, 5.55, 4.6, 1.55, "Azure Container Apps", "FastAPI (Python) — serves REST API\n+ the built React SPA, same origin",
         fill=BLUE_FILL, edge=BLUE, title_size=12.5, sub_size=9.5)

# Data / AI tier
draw_box(ax, 10.4, 6.15, 3.0, 0.95, "MongoDB Atlas", "Application data (Azure-native)", fill=GREEN_FILL, edge=GREEN)
draw_box(ax, 10.4, 4.95, 3.0, 0.95, "OpenAI GPT-4o", "CV ranking, transcript summaries, chat", fill=PURPLE_FILL, edge=PURPLE)

# Platform tier
draw_box(ax, 4.7, 3.85, 2.15, 0.95, "Azure Key Vault", "Secrets via managed identity", fill=GRAY_FILL, edge=GRAY, title_size=10.5, sub_size=8.3)
draw_box(ax, 7.15, 3.85, 2.15, 0.95, "App Insights", "Logs, traces, OpenTelemetry", fill=GRAY_FILL, edge=GRAY, title_size=10.5, sub_size=8.3)

# CI/CD tier — bottom band
draw_group_label(ax, 0.6, 2.55, "CI / CD  ·  GitHub Actions")
draw_box(ax, 0.6, 1.55, 2.55, 0.85, "Lint + Test", "flake8 · pytest · Jest", fill=AMBER_FILL, edge=AMBER, title_size=10.5, sub_size=8.3)
draw_box(ax, 3.5, 1.55, 2.75, 0.85, "Build + Push", "Docker image → ACR", fill=AMBER_FILL, edge=AMBER, title_size=10.5, sub_size=8.3)
draw_box(ax, 6.6, 1.55, 2.85, 0.85, "Deploy + Verify", "Container Apps + health check", fill=AMBER_FILL, edge=AMBER, title_size=10.5, sub_size=8.3)
draw_box(ax, 9.8, 1.55, 3.55, 0.85, "Version + Release", "SemVer tag · notes · rollback plan", fill=AMBER_FILL, edge=AMBER, title_size=10.5, sub_size=8.3)

for x1, x2 in [(3.15, 3.5), (6.25, 6.6), (9.45, 9.8)]:
    draw_arrow(ax, (x1, 1.975), (x2, 1.975), color=AMBER, lw=1.8)
draw_arrow(ax, (6.6, 2.4), (5.3, 5.55), color=AMBER, lw=1.6, curve=0.05, dashed=True)
ax.text(5.55, 3.15, "deploys new\nimage", ha="center", va="center", fontsize=8.3, color=AMBER,
        family="DejaVu Sans", zorder=5,
        bbox=dict(boxstyle="round,pad=0.2", facecolor=WHITE, edgecolor="none", alpha=0.95))

# Connections — main flow
draw_arrow(ax, (3.7, 6.38), (4.7, 6.38), color=BLUE, lw=2, label="HTTPS")
draw_arrow(ax, (9.3, 6.6), (10.4, 6.6), color=GREEN, lw=1.8, label="pymongo")
draw_arrow(ax, (9.3, 5.9), (10.4, 5.55), color=PURPLE, lw=1.8, label="OpenAI SDK")
draw_arrow(ax, (5.75, 5.55), (5.75, 4.8), color=GRAY, lw=1.5, label="secrets")
draw_arrow(ax, (8.2, 5.55), (8.2, 4.8), color=GRAY, lw=1.5, label="telemetry")

fig.tight_layout()
fig.savefig("architecture-overview.png", facecolor=WHITE, bbox_inches="tight")
plt.close(fig)
print("wrote architecture-overview.png")


# ============================================================
# DIAGRAM 2 — Detailed Architecture
# ============================================================
fig, ax = new_fig(15, 9.2)

ax.text(0.4, 8.85, "Detailed Architecture — Internal Fitment Pipeline", fontsize=17,
        fontweight="bold", color=INK, family="DejaVu Sans", ha="left")
ax.text(0.4, 8.5, "Six agents behind one A2A contract, role-scoped access, event-sourced audit trail",
        fontsize=10.5, color=INK_SOFT, family="DejaVu Sans", ha="left")

# --- Client band ---
draw_group_label(ax, 0.4, 7.95, "CLIENT — React 19 SPA")
draw_box(ax, 0.4, 7.05, 2.55, 0.7, "Pages", "Dashboard · Positions · Approvals\nAgents · Interviews · Import", fill=GRAY_FILL, edge=GRAY, title_size=9.5, sub_size=7.6)
draw_box(ax, 3.15, 7.05, 2.35, 0.7, "PersonaContext", "X-User-Id persona switcher", fill=GRAY_FILL, edge=GRAY, title_size=9.5, sub_size=7.6)
draw_box(ax, 5.7, 7.05, 2.05, 0.7, "ThemeProvider", "Dark / light mode", fill=GRAY_FILL, edge=GRAY, title_size=9.5, sub_size=7.6)

# --- Application band: FastAPI monolith with 6 agents ---
draw_group_label(ax, 0.4, 6.35, "APPLICATION — FastAPI monolith  ·  A2A agent contract (task envelopes + idempotency keys)")

agents = [
    ("Orchestrator", "status + approval gate", 0.4),
    ("Evaluation", "rank CVs vs JD", 2.55),
    ("Scheduling", "match + book interview", 4.7),
    ("Monitoring", "SLA watch + summarize", 6.85),
    ("Reporting", "scoped fulfilment reports", 9.0),
    ("Notifier", "single Slack/email exit", 11.15),
]
for name, sub, x in agents:
    draw_box(ax, x, 5.35, 1.95, 0.85, name, sub, fill=BLUE_FILL, edge=BLUE, title_size=9.8, sub_size=7.4)

draw_box(ax, 0.4, 4.35, 6.4, 0.75, "Role-scoped access layer", "scope_project_ids() / scope_filter() — every list & chat query filters through this",
         fill="#FFF7E6", edge=AMBER, title_size=9.8, sub_size=7.6)
draw_box(ax, 7.1, 4.35, 3.5, 0.75, "Pipeline / Event log / Outbox", "record_event() · notify() · idempotent by key", fill="#FFF7E6", edge=AMBER, title_size=9.3, sub_size=7.2)
draw_box(ax, 10.9, 4.35, 3.7, 0.75, "File parsing", "pypdf · python-docx (CV/JD ingest)", fill="#FFF7E6", edge=AMBER, title_size=9.3, sub_size=7.2)

# --- Data band ---
draw_group_label(ax, 0.4, 3.65, "DATA — MongoDB Atlas (Azure-native)")
draw_box(ax, 0.4, 2.7, 3.55, 0.75, "Positions · Candidates\nEvaluations", None, fill=GREEN_FILL, edge=GREEN, title_size=9.2)
draw_box(ax, 4.15, 2.7, 3.55, 0.75, "Interviews · Feedback", None, fill=GREEN_FILL, edge=GREEN, title_size=9.2)
draw_box(ax, 7.9, 2.7, 3.55, 0.75, "Approvals · Events\nOutbox · A2A tasks", None, fill=GREEN_FILL, edge=GREEN, title_size=9.2)
draw_box(ax, 11.65, 2.7, 2.95, 0.75, "Users · Projects", None, fill=GREEN_FILL, edge=GREEN, title_size=9.2)

# --- External / AI band ---
draw_group_label(ax, 0.4, 1.95, "EXTERNAL")
draw_box(ax, 0.4, 1.0, 2.9, 0.75, "OpenAI GPT-4o", "real — called by Evaluation\n+ Monitoring agents", fill=PURPLE_FILL, edge=PURPLE, title_size=9.5, sub_size=7.4)
draw_box(ax, 3.55, 1.0, 2.9, 0.75, "Slack + Email", "mocked — called by Notifier\nvia the outbox", fill=GRAY_FILL, edge=GRAY, title_size=9.5, sub_size=7.4)
draw_box(ax, 6.7, 1.0, 3.35, 0.75, "Google Workspace", "future — calendar & transcripts, mocked today", fill=GRAY_FILL, edge=GRAY, title_size=9.2, sub_size=7.0)

# --- Platform / Ops band ---
draw_group_label(ax, 10.4, 1.95, "PLATFORM")
draw_box(ax, 10.4, 1.0, 2.15, 0.75, "Key Vault", "OIDC + managed identity", fill=GRAY_FILL, edge=GRAY, title_size=9.2, sub_size=7.0)
draw_box(ax, 12.7, 1.0, 1.9, 0.75, "App Insights", "OpenTelemetry", fill=GRAY_FILL, edge=GRAY, title_size=9.2, sub_size=7.0)

# connections
draw_arrow(ax, (3.8, 7.05), (3.8, 6.2), color=GRAY, lw=1.5, label="HTTPS + X-User-Id")
for _, _, x in agents:
    draw_arrow(ax, (x + 0.97, 5.35), (x + 0.97, 5.1), color=BLUE, lw=1.1)
draw_arrow(ax, (3.5, 4.7), (3.5, 3.45), color=GREEN, lw=1.6)
draw_arrow(ax, (8.9, 4.35), (8.9, 3.45), color=GREEN, lw=1.6)

fig.tight_layout()
fig.savefig("architecture-detailed.png", facecolor=WHITE, bbox_inches="tight")
plt.close(fig)
print("wrote architecture-detailed.png")
