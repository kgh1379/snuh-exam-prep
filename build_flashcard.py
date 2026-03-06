#!/usr/bin/env python3
"""Build a self-contained flashcard HTML app from StudyVault Quiz.md files."""

import re, glob, json, os, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_DIR = os.path.join(SCRIPT_DIR, "StudyVault")
OUTPUT = os.path.join(SCRIPT_DIR, "flashcard.html")

CIRCLE_MAP = {"①": 1, "②": 2, "③": 3, "④": 4, "➃": 4, "ⓛ": 1}
CIRCLE_CHARS = r"①②③④➃ⓛ"
# Match options in both formats: "- ① text" and "> ① text" (space optional)
OPT_BULLET_RE = re.compile(rf"^-\s+([{CIRCLE_CHARS}])\s*(.+)")
OPT_BQ_RE = re.compile(rf"^>\s*([{CIRCLE_CHARS}])\s*(.+)")


def parse_quiz(path):
    """Parse a Quiz.md file → (section_name, section_num, questions_list)."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    m = re.search(r"^#\s+(.+?)\s+Quiz\s*\((\d+)문항\)", content, re.MULTILINE)
    section_name = m.group(1) if m else os.path.basename(path).replace(" Quiz.md", "")

    parent = os.path.basename(os.path.dirname(path))
    try:
        section_num = int(parent.split("-")[0])
    except (ValueError, IndexError):
        section_num = 0

    parts = re.split(r"###\s+Q(\d+)\.", content)

    questions = []
    for i in range(1, len(parts), 2):
        qnum = int(parts[i])
        block = parts[i + 1] if i + 1 < len(parts) else ""
        q = parse_question_block(block, section_num, section_name, qnum)
        if q:
            questions.append(q)

    return section_num, section_name, questions


def extract_answer(lines, block):
    """Extract answer number (1-4) from block. Handles 정답: ④ and 정답: ? patterns."""
    # Standard pattern: 정답: ①②③④
    m = re.search(r"\*\*정답:\s*([①②③④➃ⓛ])\*\*", block)
    if m:
        return CIRCLE_MAP.get(m.group(1))

    # Fallback: 정답: ? → look for leaked answer in blockquote question text
    if re.search(r"\*\*정답:\s*\?\*\*", block):
        # Find circled number at end of blockquote lines (before answer block)
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("> [!"):
                break
            if stripped.startswith("> "):
                m2 = re.search(r"[①②③④➃ⓛ]\s*$", stripped)
                if m2:
                    return CIRCLE_MAP.get(m2.group(0).strip())
        # Also check bullet lines for leaked answers like "- ④"
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("> [!"):
                break
            m2 = re.match(r"^-\s+([①②③④➃ⓛ])\s*$", stripped)
            if m2:
                return CIRCLE_MAP.get(m2.group(1))

    return None


def extract_all_markers(lines):
    """Extract option markers from ALL lines (both - ① and > ① formats)."""
    markers = []
    for j, line in enumerate(lines):
        stripped = line.strip()
        # Format 1: - ① text (bullet option)
        m = OPT_BULLET_RE.match(stripped)
        if m:
            num = CIRCLE_MAP[m.group(1)]
            text = m.group(2).strip()
            if text:  # must have actual text
                markers.append((j, num, text))
            continue
        # Format 2: > ① text (blockquote option, inside answer callout)
        m = OPT_BQ_RE.match(stripped)
        if m:
            num = CIRCLE_MAP[m.group(1)]
            text = m.group(2).strip()
            if text:
                markers.append((j, num, text))
    return markers


def parse_question_block(block, section_num, section_name, qnum):
    """Parse a single question block into a dict."""
    lines = block.split("\n")

    # 1) Find answer
    answer_num = extract_answer(lines, block)
    if answer_num is None:
        return None

    # 2) Find answer-block start line
    answer_block_idx = len(lines)
    for j, line in enumerate(lines):
        if "> [!answer]" in line:
            answer_block_idx = j
            break

    # 3) Find ALL option markers (both pre-answer and inside answer block)
    all_markers = extract_all_markers(lines)

    # 4) Find the last complete ①②③④ set
    opt_indices = find_option_set(all_markers)
    if opt_indices is None:
        return None

    # 5) Extract option text with continuations
    options = []
    first_opt_line = opt_indices[0][0]
    for k, (line_idx, num, text) in enumerate(opt_indices):
        next_line = (
            opt_indices[k + 1][0] if k + 1 < len(opt_indices) else min(line_idx + 20, len(lines))
        )
        accumulated = text
        for ci in range(line_idx + 1, next_line):
            cl = lines[ci].strip()
            # Stop at answer block boundary or next section
            if "> [!answer]" in cl or cl.startswith("### ") or cl == "---":
                break
            # Handle continuation lines (both - prefix and > prefix)
            cont = None
            if cl.startswith("- "):
                cont = cl[2:].strip()
            elif cl.startswith("> ") and line_idx >= answer_block_idx:
                # Only continue > prefix lines if option is in answer block
                cont = re.sub(r"^>\s?", "", cl).strip()

            if cont:
                if not cont:
                    continue
                if re.match(r"^[①②③④➃ⓛ]", cont):
                    break  # next option marker
                if is_continuation(accumulated, cont):
                    accumulated += " " + cont
        options.append(clean_text(accumulated))

    if len(options) != 4:
        return None

    # 6) Extract question text
    # Question text = blockquote/bullet lines before the first option
    # If first option is in answer block, use all pre-answer content
    q_end = min(first_opt_line, answer_block_idx)
    q_lines = []
    for j in range(q_end):
        line = lines[j].rstrip()
        if not line.strip():
            if q_lines:
                q_lines.append("")
            continue
        if "> [!hint]" in line or "> [!summary]" in line:
            continue
        if line.strip().startswith("> "):
            text = re.sub(r"^>\s?", "", line.strip())
            q_lines.append(text)
        elif line.strip().startswith("- "):
            text = line.strip()[2:].strip()
            # Skip standalone leaked answer markers
            if text and not re.match(r"^[①②③④➃ⓛ]$", text):
                q_lines.append(text)

    question_text = join_question_lines(q_lines)
    question_text = re.sub(r"\s+[①②③④➃ⓛ]\s*$", "", question_text)
    question_text = clean_text(question_text)

    if not question_text:
        return None

    return {
        "id": f"{section_num}_{qnum}",
        "s": section_num,
        "q": qnum,
        "text": question_text,
        "opts": options,
        "ans": answer_num,
    }


def find_option_set(markers):
    """Find the last complete ①②③④ set from marker positions."""
    result = _find_option_set_strict(markers)
    if result:
        return result

    # Fallback: fix duplicate markers (e.g. ①②③③ → ①②③④)
    if len(markers) >= 4:
        from collections import Counter

        nums = [m[1] for m in markers]
        cnt = Counter(nums)
        present = set(nums)
        missing = {1, 2, 3, 4} - present
        if len(missing) == 1:
            dup_nums = [n for n, c in cnt.items() if c > 1]
            if len(dup_nums) == 1:
                miss = missing.pop()
                dup = dup_nums[0]
                # Fix last occurrence of duplicate → missing number
                fixed = list(markers)
                for i in range(len(fixed) - 1, -1, -1):
                    if fixed[i][1] == dup:
                        fixed[i] = (fixed[i][0], miss, fixed[i][2])
                        break
                return _find_option_set_strict(fixed)
    return None


def _find_option_set_strict(markers):
    """Find the last complete ①②③④ set from marker positions."""
    idx4 = None
    for i in range(len(markers) - 1, -1, -1):
        if markers[i][1] == 4:
            idx4 = i
            break
    if idx4 is None:
        return None

    idx3 = None
    for i in range(idx4 - 1, -1, -1):
        if markers[i][1] == 3:
            idx3 = i
            break

    idx2 = None
    if idx3 is not None:
        for i in range(idx3 - 1, -1, -1):
            if markers[i][1] == 2:
                idx2 = i
                break

    idx1 = None
    if idx2 is not None:
        for i in range(idx2 - 1, -1, -1):
            if markers[i][1] == 1:
                idx1 = i
                break

    if any(x is None for x in [idx1, idx2, idx3, idx4]):
        return None

    return [markers[idx1], markers[idx2], markers[idx3], markers[idx4]]


def is_continuation(accumulated, next_text):
    """Check if next_text continues the accumulated option text."""
    # Sub-option markers always continue
    if re.match(r"^[ㄱ-ㅎ]\)", next_text):
        return True
    # If accumulated ends with period → complete sentence → not continuation
    stripped = accumulated.rstrip()
    if stripped.endswith(".") or stripped.endswith("다."):
        return False
    return True


def join_question_lines(lines):
    """Join question lines: consecutive non-empty lines with space, blank lines as \\n."""
    result = []
    current = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        else:
            if current:
                result.append(" ".join(current))
                current = []
    if current:
        result.append(" ".join(current))
    return "\n".join(result)


def clean_text(text):
    """Clean up text: normalize whitespace, strip."""
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def build_all():
    """Parse all Quiz.md files and return structured data."""
    quiz_files = sorted(glob.glob(os.path.join(VAULT_DIR, "*", "*Quiz.md")))
    if not quiz_files:
        print(f"Error: No Quiz.md files found in {VAULT_DIR}/*/", file=sys.stderr)
        sys.exit(1)

    sections = []
    all_questions = []

    for path in quiz_files:
        section_num, section_name, questions = parse_quiz(path)
        sections.append(
            {"id": section_num, "name": section_name, "count": len(questions)}
        )
        all_questions.extend(questions)
        print(f"  [{section_num:2d}] {section_name}: {len(questions)} questions")

    sections.sort(key=lambda s: s["id"])
    all_questions.sort(key=lambda q: (q["s"], q["q"]))

    return {"sections": sections, "questions": all_questions}


# ── HTML Template ──────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<title>StudyVault Flashcard</title>
<style>
:root {
  --bg: #f0f2f5; --card: #ffffff; --text: #1a1a2e; --text2: #555;
  --muted: #8e8e93; --border: #e0e0e0; --primary: #4A90D9;
  --primary-light: rgba(74,144,217,0.12); --correct: #27ae60;
  --correct-bg: rgba(39,174,96,0.12); --wrong-opacity: 0.35;
  --option-bg: #f8f9fa; --shadow: 0 2px 8px rgba(0,0,0,0.08);
  --ctrl-bg: #ffffff; --chip-bg: #e8e8ed; --chip-active: var(--primary);
  --header-bg: #ffffff; --overlay: rgba(0,0,0,0.5);
}
.dark {
  --bg: #0d1117; --card: #161b22; --text: #e6edf3; --text2: #aaa;
  --muted: #8b949e; --border: #30363d; --primary: #58a6ff;
  --primary-light: rgba(88,166,255,0.15); --correct: #3fb950;
  --correct-bg: rgba(63,185,80,0.15); --option-bg: #21262d;
  --shadow: 0 2px 8px rgba(0,0,0,0.3); --ctrl-bg: #161b22;
  --chip-bg: #30363d; --header-bg: #161b22; --overlay: rgba(0,0,0,0.7);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{height:100dvh;height:100vh}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
  background:var(--bg);color:var(--text);height:100dvh;height:100vh;overflow:hidden;
  -webkit-tap-highlight-color:transparent;-webkit-user-select:none;user-select:none}
button{font:inherit;cursor:pointer;border:none;background:none;color:inherit;
  -webkit-tap-highlight-color:transparent}
.view{display:none;height:100dvh;height:100vh;flex-direction:column;overflow:hidden}
.view.active{display:flex}

/* ── Header ── */
.hdr{display:flex;align-items:center;padding:12px 16px;background:var(--header-bg);
  border-bottom:1px solid var(--border);min-height:52px;gap:12px}
.hdr h1{font-size:17px;font-weight:700;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hdr-btn{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:18px;flex-shrink:0;transition:background .2s}
.hdr-btn:active{background:var(--primary-light)}

/* ── Home ── */
.home-top{text-align:center;padding:28px 16px 20px}
.home-top h1{font-size:22px;font-weight:800;letter-spacing:-0.3px}
.home-top p{font-size:13px;color:var(--muted);margin-top:6px}
.all-btn{display:block;margin:0 16px 16px;padding:14px;border-radius:12px;
  background:var(--primary);color:#fff;font-size:15px;font-weight:700;text-align:center;
  transition:opacity .2s}
.all-btn:active{opacity:.8}
.all-count{font-weight:400;opacity:.8;margin-left:6px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;padding:0 16px 100px;
  overflow-y:auto;-webkit-overflow-scrolling:touch}
.card{background:var(--card);border-radius:14px;padding:16px;box-shadow:var(--shadow);
  transition:transform .15s;cursor:pointer;border:1px solid var(--border)}
.card:active{transform:scale(.97)}
.card-num{font-size:26px;font-weight:800;color:var(--primary)}
.card-name{font-size:12.5px;line-height:1.45;margin-top:8px;color:var(--text);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card-count{font-size:11.5px;color:var(--muted);margin-top:6px}
.nav-bar{display:flex;position:fixed;bottom:0;left:0;right:0;background:var(--header-bg);
  border-top:1px solid var(--border);padding:8px 0 env(safe-area-inset-bottom,8px)}
.nav-item{flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;
  padding:6px 0;font-size:10px;color:var(--muted);transition:color .2s}
.nav-item.active{color:var(--primary)}
.nav-item span:first-child{font-size:20px}

/* ── Player ── */
.player-info{display:flex;align-items:center;padding:10px 16px;gap:8px;
  background:var(--header-bg);border-bottom:1px solid var(--border)}
.player-section{font-size:13px;color:var(--muted);flex:1;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.player-progress{font-size:13px;font-weight:600;color:var(--primary);white-space:nowrap}
.player-close{font-size:20px;margin-left:8px;padding:4px}
.timer-track{height:3px;background:var(--border);position:relative;flex-shrink:0}
.timer-bar{height:100%;background:var(--primary);width:100%;transition:none}
.card-area{flex:1;overflow-y:auto;padding:20px 16px 16px;-webkit-overflow-scrolling:touch}
.q-badge{display:inline-block;background:var(--primary);color:#fff;border-radius:14px;
  padding:3px 12px;font-size:12px;font-weight:700;letter-spacing:0.5px}
.q-text{font-size:15px;line-height:1.7;margin-top:14px;white-space:pre-line;word-break:keep-all}
.opts{margin-top:18px;display:flex;flex-direction:column;gap:8px}
.opt{padding:12px 14px;border-radius:10px;background:var(--option-bg);font-size:14px;
  line-height:1.55;border:2px solid transparent;transition:all .35s;word-break:keep-all}
.opt .marker{font-weight:700;margin-right:6px}
.opt.correct{background:var(--correct-bg);border-color:var(--correct);font-weight:600}
.opt.correct .marker{color:var(--correct)}
.opt.wrong{opacity:var(--wrong-opacity)}
.controls{display:flex;align-items:center;justify-content:space-around;
  padding:10px 24px env(safe-area-inset-bottom,12px);background:var(--ctrl-bg);
  border-top:1px solid var(--border);flex-shrink:0}
.ctrl{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:22px;transition:background .2s,transform .15s}
.ctrl:active{transform:scale(.9);background:var(--primary-light)}
.ctrl.primary-bg{background:var(--primary);color:#fff;font-size:20px}
.ctrl.primary-bg:active{opacity:.8}
.ctrl.bookmarked{color:#f59e0b}
.done-overlay{position:absolute;inset:0;background:var(--overlay);display:flex;
  align-items:center;justify-content:center;z-index:10}
.done-box{background:var(--card);border-radius:20px;padding:32px 28px;text-align:center;
  max-width:300px;width:85%}
.done-box h2{font-size:22px;margin-bottom:8px}
.done-box p{font-size:14px;color:var(--muted);margin-bottom:20px}
.done-btn{display:block;width:100%;padding:12px;border-radius:10px;font-size:14px;
  font-weight:600;margin-bottom:8px;transition:opacity .2s}
.done-btn.pri{background:var(--primary);color:#fff}
.done-btn.sec{background:var(--chip-bg);color:var(--text)}

/* ── Bookmarks ── */
.bm-empty{text-align:center;padding:60px 20px;color:var(--muted)}
.bm-empty span{font-size:48px;display:block;margin-bottom:12px}
.bm-list{overflow-y:auto;padding:12px 16px 100px;-webkit-overflow-scrolling:touch;flex:1}
.bm-item{background:var(--card);border-radius:12px;padding:14px;margin-bottom:8px;
  box-shadow:var(--shadow);display:flex;align-items:flex-start;gap:12px;cursor:pointer;
  border:1px solid var(--border);transition:transform .15s}
.bm-item:active{transform:scale(.98)}
.bm-badge{background:var(--primary-light);color:var(--primary);border-radius:8px;
  padding:4px 8px;font-size:11px;font-weight:700;white-space:nowrap;flex-shrink:0}
.bm-text{flex:1;font-size:13px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;overflow:hidden}
.bm-del{color:var(--muted);font-size:18px;padding:0 4px;flex-shrink:0}

/* ── Settings ── */
.settings-scroll{overflow-y:auto;padding:16px;flex:1;-webkit-overflow-scrolling:touch}
.st-group{margin-bottom:24px}
.st-label{font-size:13px;font-weight:700;color:var(--muted);text-transform:uppercase;
  letter-spacing:0.5px;margin-bottom:10px}
.st-chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{padding:8px 18px;border-radius:20px;background:var(--chip-bg);font-size:14px;
  font-weight:500;transition:all .2s}
.chip.active{background:var(--chip-active);color:#fff}
.toggle-row{display:flex;align-items:center;justify-content:space-between;
  padding:14px 0;border-bottom:1px solid var(--border)}
.toggle-row:last-child{border:none}
.toggle-label{font-size:15px}
.toggle{width:50px;height:28px;border-radius:14px;background:var(--chip-bg);
  position:relative;transition:background .3s;flex-shrink:0}
.toggle.on{background:var(--primary)}
.toggle::after{content:'';position:absolute;width:22px;height:22px;border-radius:50%;
  background:#fff;top:3px;left:3px;transition:transform .3s;box-shadow:0 1px 3px rgba(0,0,0,.2)}
.toggle.on::after{transform:translateX(22px)}

/* ── Animations ── */
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.fade-in{animation:fadeIn .3s ease}
@keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.15)}}
.pulse{animation:pulse .3s ease}
</style>
</head>
<body>

<!-- ═══ HOME ═══ -->
<div id="v-home" class="view active">
  <div class="home-top">
    <h1>StudyVault</h1>
    <p>플래시카드로 빠르게 반복 학습</p>
  </div>
  <button class="all-btn" onclick="startAll()">
    전체 문제<span class="all-count" id="total-count"></span>
  </button>
  <div class="grid" id="section-grid"></div>
  <div class="nav-bar">
    <button class="nav-item active" onclick="showView('home')"><span>📋</span>홈</button>
    <button class="nav-item" onclick="showView('bookmarks')"><span>⭐</span>북마크</button>
    <button class="nav-item" onclick="showView('settings')"><span>⚙</span>설정</button>
  </div>
</div>

<!-- ═══ PLAYER ═══ -->
<div id="v-player" class="view" style="position:relative">
  <div class="player-info">
    <span class="player-section" id="p-section"></span>
    <span class="player-progress" id="p-progress"></span>
    <button class="player-close" onclick="closePlayer()">✕</button>
  </div>
  <div class="timer-track"><div class="timer-bar" id="timer-bar"></div></div>
  <div class="card-area" id="card-area"></div>
  <div class="controls">
    <button class="ctrl" onclick="prevQ()" title="이전 (←)">◀</button>
    <button class="ctrl primary-bg" id="btn-pause" onclick="togglePause()" title="일시정지 (Space)">⏸</button>
    <button class="ctrl" onclick="nextQ()" title="다음 (→)">▶</button>
    <button class="ctrl" id="btn-bm" onclick="toggleBookmark()" title="북마크 (B)">☆</button>
  </div>
  <div class="done-overlay" id="done-overlay" style="display:none">
    <div class="done-box fade-in">
      <h2>학습 완료!</h2>
      <p id="done-msg"></p>
      <button class="done-btn pri" onclick="restartSection()">다시 시작</button>
      <button class="done-btn sec" onclick="closePlayer()">홈으로</button>
    </div>
  </div>
</div>

<!-- ═══ BOOKMARKS ═══ -->
<div id="v-bookmarks" class="view">
  <div class="hdr">
    <button class="hdr-btn" onclick="showView('home')">←</button>
    <h1>북마크</h1>
    <button class="hdr-btn" id="bm-clear-btn" onclick="clearAllBookmarks()" title="전체 삭제">🗑</button>
  </div>
  <div id="bm-content" style="flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch"></div>
  <div class="nav-bar">
    <button class="nav-item" onclick="showView('home')"><span>📋</span>홈</button>
    <button class="nav-item active" onclick="showView('bookmarks')"><span>⭐</span>북마크</button>
    <button class="nav-item" onclick="showView('settings')"><span>⚙</span>설정</button>
  </div>
</div>

<!-- ═══ SETTINGS ═══ -->
<div id="v-settings" class="view">
  <div class="hdr">
    <button class="hdr-btn" onclick="showView('home')">←</button>
    <h1>설정</h1>
  </div>
  <div class="settings-scroll">
    <div class="st-group">
      <div class="st-label">문제 표시 시간</div>
      <div class="st-chips" id="st-qtime"></div>
    </div>
    <div class="st-group">
      <div class="st-label">정답 표시 시간</div>
      <div class="st-chips" id="st-atime"></div>
    </div>
    <div class="st-group">
      <div class="toggle-row">
        <span class="toggle-label">다크 모드</span>
        <button class="toggle" id="tgl-dark" onclick="toggleDark()"></button>
      </div>
      <div class="toggle-row">
        <span class="toggle-label">셔플 모드</span>
        <button class="toggle" id="tgl-shuffle" onclick="toggleShuffle()"></button>
      </div>
    </div>
  </div>
  <div class="nav-bar">
    <button class="nav-item" onclick="showView('home')"><span>📋</span>홈</button>
    <button class="nav-item" onclick="showView('bookmarks')"><span>⭐</span>북마크</button>
    <button class="nav-item active" onclick="showView('settings')"><span>⚙</span>설정</button>
  </div>
</div>

<script>
// ── Data ──
const DATA = %%DATA%%;
const SECTIONS = DATA.sections;
const ALL_Q = DATA.questions;
const MARKERS = ['①','②','③','④'];

// ── State ──
let settings = loadJSON('sv_settings', {
  questionTime: 10, answerTime: 3, dark: false, shuffle: false
});
let bookmarks = new Set(loadJSON('sv_bookmarks', []));
let progress = loadJSON('sv_progress', {});

let player = {
  questions: [], idx: 0, phase: 'question', playing: true,
  sectionId: null, sectionName: '', timer: null, timerStart: 0,
  timerDuration: 0, paused: false, pauseRemaining: 0
};

// ── Persistence ──
function loadJSON(key, def) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : def; }
  catch { return def; }
}
function saveSettings() { localStorage.setItem('sv_settings', JSON.stringify(settings)); }
function saveBookmarks() { localStorage.setItem('sv_bookmarks', JSON.stringify([...bookmarks])); }
function saveProgress() { localStorage.setItem('sv_progress', JSON.stringify(progress)); }

// ── Theme ──
function applyTheme() {
  document.body.classList.toggle('dark', settings.dark);
  const tgl = document.getElementById('tgl-dark');
  if (tgl) tgl.classList.toggle('on', settings.dark);
}
applyTheme();

// ── Views ──
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('v-' + name).classList.add('active');
  // Update nav highlights
  document.querySelectorAll('.nav-bar').forEach(bar => {
    bar.querySelectorAll('.nav-item').forEach((btn, i) => {
      const views = ['home','bookmarks','settings'];
      btn.classList.toggle('active', views[i] === name);
    });
  });
  if (name === 'bookmarks') renderBookmarks();
  if (name === 'settings') renderSettings();
  if (name === 'home') renderHome();
}

// ── Home ──
function renderHome() {
  const grid = document.getElementById('section-grid');
  document.getElementById('total-count').textContent = '(' + ALL_Q.length + '문항)';
  grid.innerHTML = SECTIONS.map(s => {
    const done = progress[s.id] || 0;
    return '<div class="card" onclick="startSection(' + s.id + ')">' +
      '<div class="card-num">' + String(s.id).padStart(2,'0') + '</div>' +
      '<div class="card-name">' + esc(s.name) + '</div>' +
      '<div class="card-count">' + s.count + '문항' +
        (done > 0 ? ' · 진행 ' + done + '/' + s.count : '') +
      '</div></div>';
  }).join('');
}

// ── Player ──
function startSection(sid) {
  const qs = ALL_Q.filter(q => q.s === sid);
  if (!qs.length) return;
  const sec = SECTIONS.find(s => s.id === sid);
  player.sectionId = sid;
  player.sectionName = sec ? sec.name : '';
  player.questions = settings.shuffle ? shuffle([...qs]) : [...qs];
  player.idx = Math.min(progress[sid] || 0, player.questions.length - 1);
  player.phase = 'question';
  player.playing = true;
  player.paused = false;
  showView('player');
  document.getElementById('done-overlay').style.display = 'none';
  renderCard();
  startTimer();
}

function startAll() {
  player.sectionId = 'all';
  player.sectionName = '전체 문제';
  player.questions = settings.shuffle ? shuffle([...ALL_Q]) : [...ALL_Q];
  player.idx = Math.min(progress['all'] || 0, player.questions.length - 1);
  player.phase = 'question';
  player.playing = true;
  player.paused = false;
  showView('player');
  document.getElementById('done-overlay').style.display = 'none';
  renderCard();
  startTimer();
}

function renderCard() {
  const q = player.questions[player.idx];
  if (!q) return;
  document.getElementById('p-section').textContent = player.sectionName;
  document.getElementById('p-progress').textContent =
    (player.idx + 1) + ' / ' + player.questions.length;
  // Bookmark button
  document.getElementById('btn-bm').className =
    'ctrl' + (bookmarks.has(q.id) ? ' bookmarked' : '');
  document.getElementById('btn-bm').textContent = bookmarks.has(q.id) ? '★' : '☆';
  // Pause button
  document.getElementById('btn-pause').textContent = player.paused ? '▶' : '⏸';

  const area = document.getElementById('card-area');
  const sec = SECTIONS.find(s => s.id === q.s);
  const secLabel = sec ? String(sec.id).padStart(2,'0') : '';

  let html = '<div class="fade-in">';
  html += '<span class="q-badge">' + secLabel + ' - Q' + q.q + '</span>';
  html += '<div class="q-text">' + esc(q.text) + '</div>';
  html += '<div class="opts">';
  for (let i = 0; i < q.opts.length; i++) {
    let cls = 'opt';
    if (player.phase === 'answer') {
      cls += (i + 1 === q.ans) ? ' correct' : ' wrong';
    }
    html += '<div class="' + cls + '">' +
      '<span class="marker">' + MARKERS[i] + '</span> ' + esc(q.opts[i]) + '</div>';
  }
  html += '</div></div>';
  area.innerHTML = html;
  area.scrollTop = 0;

  // Save progress
  progress[player.sectionId] = player.idx;
  saveProgress();
}

// ── Timer ──
function startTimer() {
  clearTimer();
  const dur = (player.phase === 'question'
    ? settings.questionTime : settings.answerTime) * 1000;
  player.timerDuration = dur;
  player.timerStart = performance.now();
  player.pauseRemaining = 0;
  updateTimerBar();
  player.timer = requestAnimationFrame(tickTimer);
}

function tickTimer(now) {
  if (player.paused) return;
  const elapsed = now - player.timerStart;
  const remaining = Math.max(0, player.timerDuration - elapsed);
  const pct = remaining / player.timerDuration;
  setBarWidth(pct);

  if (remaining <= 0) {
    onTimerEnd();
  } else {
    player.timer = requestAnimationFrame(tickTimer);
  }
}

function updateTimerBar() {
  setBarWidth(1);
}

function setBarWidth(pct) {
  const bar = document.getElementById('timer-bar');
  bar.style.width = (pct * 100) + '%';
  if (pct > 0.5) bar.style.background = 'var(--primary)';
  else if (pct > 0.2) bar.style.background = '#f39c12';
  else bar.style.background = '#e74c3c';
}

function clearTimer() {
  if (player.timer) cancelAnimationFrame(player.timer);
  player.timer = null;
}

function onTimerEnd() {
  clearTimer();
  if (player.phase === 'question') {
    showAnswer();
  } else {
    goNext();
  }
}

function showAnswer() {
  player.phase = 'answer';
  renderCard();
  startTimer();
}

function goNext() {
  if (player.idx + 1 >= player.questions.length) {
    clearTimer();
    showDone();
    return;
  }
  player.idx++;
  player.phase = 'question';
  renderCard();
  startTimer();
}

function showDone() {
  document.getElementById('done-msg').textContent =
    player.questions.length + '문항 학습 완료!';
  document.getElementById('done-overlay').style.display = 'flex';
  setBarWidth(0);
}

function restartSection() {
  document.getElementById('done-overlay').style.display = 'none';
  player.idx = 0;
  player.phase = 'question';
  player.playing = true;
  player.paused = false;
  if (settings.shuffle) player.questions = shuffle([...player.questions]);
  renderCard();
  startTimer();
}

function closePlayer() {
  clearTimer();
  showView('home');
}

// ── Controls ──
function prevQ() {
  if (player.idx <= 0) return;
  player.idx--;
  player.phase = 'question';
  player.paused = false;
  renderCard();
  startTimer();
}

function nextQ() {
  player.phase = 'question';
  player.paused = false;
  goNext();
}

function togglePause() {
  if (player.paused) {
    // Resume
    player.paused = false;
    player.timerStart = performance.now() - (player.timerDuration - player.pauseRemaining);
    player.timer = requestAnimationFrame(tickTimer);
  } else {
    // Pause
    player.paused = true;
    const elapsed = performance.now() - player.timerStart;
    player.pauseRemaining = Math.max(0, player.timerDuration - elapsed);
    clearTimer();
  }
  document.getElementById('btn-pause').textContent = player.paused ? '▶' : '⏸';
}

function toggleBookmark() {
  const q = player.questions[player.idx];
  if (!q) return;
  if (bookmarks.has(q.id)) bookmarks.delete(q.id);
  else bookmarks.add(q.id);
  saveBookmarks();
  document.getElementById('btn-bm').className =
    'ctrl' + (bookmarks.has(q.id) ? ' bookmarked' : '');
  document.getElementById('btn-bm').textContent = bookmarks.has(q.id) ? '★' : '☆';
  // Pulse animation
  const btn = document.getElementById('btn-bm');
  btn.classList.remove('pulse');
  void btn.offsetWidth;
  btn.classList.add('pulse');
}

// ── Bookmarks View ──
function renderBookmarks() {
  const el = document.getElementById('bm-content');
  const bmQuestions = ALL_Q.filter(q => bookmarks.has(q.id));

  if (bmQuestions.length === 0) {
    el.innerHTML = '<div class="bm-empty"><span>☆</span>북마크한 문제가 없습니다</div>';
    document.getElementById('bm-clear-btn').style.display = 'none';
    return;
  }
  document.getElementById('bm-clear-btn').style.display = '';

  // "전체 북마크" button
  let html = '<div style="padding:24px 16px 12px">';
  html += '<button class="all-btn" onclick="playBmAll()" style="margin:0">';
  html += '전체 북마크 셔플<span class="all-count">(' + bmQuestions.length + '문항)</span></button>';
  html += '</div>';

  // Per-section cards (only sections with bookmarks)
  const secCounts = {};
  bmQuestions.forEach(q => { secCounts[q.s] = (secCounts[q.s] || 0) + 1; });
  const secs = SECTIONS.filter(s => secCounts[s.id]);

  html += '<div class="grid" style="padding:0 16px 100px">';
  html += secs.map(s => {
    const cnt = secCounts[s.id];
    return '<div class="card" onclick="playBmSection(' + s.id + ')" style="border-left:3px solid #f59e0b">' +
      '<div class="card-num" style="color:#f59e0b">★ ' + String(s.id).padStart(2,'0') + '</div>' +
      '<div class="card-name">' + esc(s.name) + '</div>' +
      '<div class="card-count">북마크 ' + cnt + '문항</div></div>';
  }).join('');
  html += '</div>';

  el.innerHTML = html;
}

function playBmAll() {
  const qs = ALL_Q.filter(q => bookmarks.has(q.id));
  if (!qs.length) return;
  player.sectionId = 'bm_all';
  player.sectionName = '★ 전체 북마크';
  player.questions = shuffle([...qs]);
  player.idx = 0;
  player.phase = 'question';
  player.playing = true;
  player.paused = false;
  showView('player');
  document.getElementById('done-overlay').style.display = 'none';
  renderCard();
  startTimer();
}

function playBmSection(sid) {
  const qs = ALL_Q.filter(q => q.s === sid && bookmarks.has(q.id));
  if (!qs.length) return;
  const sec = SECTIONS.find(s => s.id === sid);
  player.sectionId = 'bm_' + sid;
  player.sectionName = '★ ' + (sec ? sec.name : '');
  player.questions = shuffle([...qs]);
  player.idx = 0;
  player.phase = 'question';
  player.playing = true;
  player.paused = false;
  showView('player');
  document.getElementById('done-overlay').style.display = 'none';
  renderCard();
  startTimer();
}

function clearAllBookmarks() {
  if (!confirm('모든 북마크를 삭제할까요?')) return;
  bookmarks.clear();
  saveBookmarks();
  renderBookmarks();
}

// ── Settings View ──
function renderSettings() {
  renderChips('st-qtime', [5,10,15,20], settings.questionTime, '초',
    v => { settings.questionTime = v; saveSettings(); renderSettings(); });
  renderChips('st-atime', [1,2,3], settings.answerTime, '초',
    v => { settings.answerTime = v; saveSettings(); renderSettings(); });
  document.getElementById('tgl-dark').classList.toggle('on', settings.dark);
  document.getElementById('tgl-shuffle').classList.toggle('on', settings.shuffle);
}

function renderChips(containerId, values, current, suffix, onChange) {
  const el = document.getElementById(containerId);
  el.innerHTML = values.map(v =>
    '<button class="chip' + (v === current ? ' active' : '') + '" ' +
    'onclick="this._cb(' + v + ')">' + v + suffix + '</button>'
  ).join('');
  el.querySelectorAll('.chip').forEach((btn, i) => {
    btn._cb = onChange;
  });
}

function toggleDark() {
  settings.dark = !settings.dark;
  saveSettings();
  applyTheme();
  renderSettings();
}

function toggleShuffle() {
  settings.shuffle = !settings.shuffle;
  saveSettings();
  document.getElementById('tgl-shuffle').classList.toggle('on', settings.shuffle);
}

// ── Touch Swipe ──
let touchX = 0, touchY = 0;
document.addEventListener('touchstart', e => {
  touchX = e.touches[0].clientX;
  touchY = e.touches[0].clientY;
}, {passive: true});
document.addEventListener('touchend', e => {
  if (!document.getElementById('v-player').classList.contains('active')) return;
  const dx = e.changedTouches[0].clientX - touchX;
  const dy = e.changedTouches[0].clientY - touchY;
  if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 60) {
    if (dx < 0) nextQ(); else prevQ();
  }
}, {passive: true});

// ── Keyboard ──
document.addEventListener('keydown', e => {
  if (!document.getElementById('v-player').classList.contains('active')) return;
  if (e.key === 'ArrowRight' || e.key === 'l') nextQ();
  else if (e.key === 'ArrowLeft' || e.key === 'h') prevQ();
  else if (e.key === ' ') { e.preventDefault(); togglePause(); }
  else if (e.key === 'b' || e.key === 'B') toggleBookmark();
  else if (e.key === 'Escape') closePlayer();
});

// ── Tap to reveal answer early ──
document.addEventListener('click', e => {
  if (!document.getElementById('v-player').classList.contains('active')) return;
  if (e.target.closest('.opt') && player.phase === 'question' && !player.paused) {
    clearTimer();
    showAnswer();
  }
});

// ── Utilities ──
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// ── Init ──
renderHome();
</script>
</body>
</html>"""


def main():
    print("Parsing Quiz.md files...")
    data = build_all()
    total = len(data["questions"])
    print(f"\nTotal: {len(data['sections'])} sections, {total} questions")

    # Embed JSON in HTML
    json_str = json.dumps(data, ensure_ascii=False)
    json_str = json_str.replace("</", "<\\/")  # prevent script break-out

    html = HTML_TEMPLATE.replace("%%DATA%%", json_str)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✓ Generated: {OUTPUT}")
    print(f"  Open in browser to start studying!")


if __name__ == "__main__":
    main()
