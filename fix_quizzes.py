#!/usr/bin/env python3
"""
fix_quizzes.py — Parse all 12 quiz MD files, fix formatting issues, rewrite clean
MD files, and update the JSON DATA in index.html.

Issues fixed:
1. Broken spacing from PDF line breaks (continuation lines joined)
2. Explanation/hint text leaked into options → captured and merged into answer block
3. Missing options (②③④ inside answer block → reconstructed)
4. Answer number leaked into question text (removed)
5. Options embedded in blockquote (question) area
6. Duplicate option markers (e.g., two ③ → treat second as ④)
7. Special markers ①②③④ → normalized to 1. 2. 3. 4. in output
8. Orphaned non-marker lines before first option → treated as question continuation
"""

import re
import json
import os

BASE = "/Users/momo/Documents/test"
VAULT = os.path.join(BASE, "StudyVault")
INDEX_HTML = os.path.join(BASE, "index.html")

SECTIONS = [
    (1, "01-감사규정-부정청탁금지법-이해충돌방지법", "감사규정, 부정청탁금지법, 이해충돌방지법 Quiz.md"),
    (2, "02-설치법-병원정관-직제규정", "설치법, 병원정관, 직제규정 Quiz.md"),
    (3, "03-인사규정-복무규정-근로기준법", "인사규정, 복무규정, 근로기준법 등 Quiz.md"),
    (4, "04-보수규정-복리후생관리내규", "보수규정, 복리후생관리내규 Quiz.md"),
    (5, "05-단체협약-복리후생-노무", "단체협약, 복리후생, 노무 Quiz.md"),
    (6, "06-병원기본교육", "병원 기본교육 Quiz.md"),
    (7, "07-병원역사", "병원 역사 Quiz.md"),
    (8, "08-원무보험", "원무·보험 Quiz.md"),
    (9, "09-재무회계", "재무회계 Quiz.md"),
    (10, "10-병원인증평가", "병원 인증평가 Quiz.md"),
    (11, "11-산업안전보건-중대재해처벌법", "산업안전보건, 중대재해처벌법 Quiz.md"),
    (12, "12-공공의료", "공공의료 Quiz.md"),
]

MARKER_MAP = {'①': 1, '②': 2, '③': 3, '④': 4, '⑤': 5}
MARKER_MAP_EXTRA = {'➀': 1, '➁': 2, '➂': 3, '➃': 4, 'ⓛ': 1}
ALL_MARKERS = {**MARKER_MAP, **MARKER_MAP_EXTRA}

# All circled number chars for normalization
CIRCLED_CHARS = {
    '①': '1', '②': '2', '③': '3', '④': '4', '⑤': '5',
    '➀': '1', '➁': '2', '➂': '3', '➃': '4',
    'ⓛ': '1', '⓷': '3',
}

# Parenthesized Hangul Jamo → plain Jamo
CIRCLED_HANGUL = {
    '㉠': 'ㄱ', '㉡': 'ㄴ', '㉢': 'ㄷ', '㉣': 'ㄹ', '㉤': 'ㅁ', '㉥': 'ㅂ',
    '㉦': 'ㅅ', '㉧': 'ㅇ', '㉨': 'ㅈ', '㉩': 'ㅊ', '㉪': 'ㅋ', '㉫': 'ㅌ',
    '㉬': 'ㅍ', '㉭': 'ㅎ',
}


def normalize_special_chars(text):
    """Normalize all special marker characters:
    - ①②③④ → 1), 2), 3), 4) (when followed by text) or 1, 2, 3, 4
    - ㉠㉡㉢㉣ → ㄱ, ㄴ, ㄷ, ㄹ
    - Ensure spacing before 가. 나. 다. 라. sub-labels
    """
    # Circled numbers → plain digits
    for old, new in CIRCLED_CHARS.items():
        text = re.sub(re.escape(old) + r'(?=[가-힣0-9])', new + ')', text)
        text = text.replace(old, new)

    # Parenthesized Hangul → plain Jamo
    for old, new in CIRCLED_HANGUL.items():
        text = text.replace(old, new)

    # Fix missing space before sub-labels (가. 나. 다. 라. 마. 바. 사.)
    # e.g., "방안나." → "방안 나." (Korean char directly before label)
    # But NOT verb endings: 한다. 된다. 있다. 없다. 않다. etc.
    # Chars that form verb endings with 다 (한다, 됐다, 있다, 했다, 는다, etc.)
    VERB_BEFORE_DA = set('한된있없않할될줄낼올갈볼하보이했는니었였났았갔왔봤셨겠렸')

    def _fix_sublabel(m):
        prev_char, label = m.group(1), m.group(2)
        if label == '다' and prev_char in VERB_BEFORE_DA:
            return m.group(0)
        return f'{prev_char} {label}. '

    text = re.sub(r'([가-힣])([가나다라마바사아자차카타파하])\. ', _fix_sublabel, text)

    return text


def smart_join(parts):
    """Join text parts, detecting mid-word Korean splits."""
    if not parts:
        return ''
    if len(parts) == 1:
        return parts[0]

    result = parts[0]
    for i in range(1, len(parts)):
        prev = result
        curr = parts[i]
        if not prev or not curr:
            result = result + ' ' + curr if curr else result
            continue

        prev_ends_korean = bool(re.search(r'[가-힣]$', prev))
        mid_word_match = re.match(r'^([가-힣]{1,3})([^가-힣]|$)', curr)

        if prev_ends_korean and mid_word_match:
            result = result + curr
        else:
            result = result + ' ' + curr

    return result


def fix_spacing(text):
    """Fix spurious spaces from PDF line breaks."""
    if not text:
        return text

    known_joins = [
        # "한 다." → "한다." (PDF line-break artifact, never valid Korean spacing)
        (r'한 다\.', '한다.'),
        (r'된 다\.', '된다.'),
        (r'없 다\.', '없다.'),
        (r'있 다\.', '있다.'),
        (r'않 다\.', '않다.'),
        (r'든 다\.', '든다.'),
        (r'할 수 있 다', '할 수 있다'),
        (r'할 수 없 다', '할 수 없다'),
        (r'하여 야', '하여야'),
        (r'않아 야', '않아야'),
        (r'되어 야', '되어야'),
        (r'어 야 한다', '어야 한다'),
        (r'위 촉', '위촉'),
        (r'서 서 ', '서서 '),
        (r'넘 을', '넘을'),
        (r'않 은', '않은'),
        (r'보 기 ', '보기 '),
    ]
    for pattern, replacement in known_joins:
        text = re.sub(pattern, replacement, text)
    return text


def detect_marker_at_start(text):
    """Check if text starts with a circled number marker.
    Returns (marker_num, remaining_text) or (None, text)."""
    for marker_char, marker_num in ALL_MARKERS.items():
        if text.startswith(marker_char):
            remaining = text[len(marker_char):].strip()
            return marker_num, remaining
    return None, text


def strip_trailing_answer_marker(text):
    """Remove trailing ①②③④ markers from question text (leaked answers)."""
    text = text.rstrip()
    for m in list(ALL_MARKERS.keys()):
        if text.endswith(m):
            text = text[:-len(m)].rstrip()
    return text


def parse_question_block(lines, sec_num=0):
    """Parse a single question block."""
    result = {
        'q_num': None,
        'question_text': '',
        'options': {},
        'answer': None,
        'explanation': '',
    }

    if not lines:
        return result

    first_line = lines[0].strip()
    m = re.match(r'###\s+Q(\d+)\.', first_line)
    if m:
        result['q_num'] = int(m.group(1))

    # Categorize lines
    question_lines = []
    option_lines = []
    answer_lines = []
    state = 'pre'

    for line in lines[1:]:
        stripped = line.strip()

        if state == 'pre':
            if stripped == '':
                continue
            if stripped.startswith('>'):
                if '[!answer]' in stripped:
                    state = 'answer'
                    answer_lines.append(stripped)
                else:
                    state = 'question'
                    question_lines.append(stripped)
            elif stripped.startswith('- '):
                state = 'options'
                option_lines.append(stripped)
            continue

        if state == 'question':
            if stripped.startswith('>'):
                if '[!answer]' in stripped:
                    state = 'answer'
                    answer_lines.append(stripped)
                else:
                    question_lines.append(stripped)
            elif stripped.startswith('- '):
                state = 'options'
                option_lines.append(stripped)
            elif stripped == '':
                continue
            else:
                question_lines.append(stripped)
            continue

        if state == 'options':
            if stripped.startswith('>'):
                state = 'answer'
                answer_lines.append(stripped)
            elif stripped == '':
                continue
            else:
                option_lines.append(stripped)
            continue

        if state == 'answer':
            answer_lines.append(stripped)
            continue

    # --- Parse question text ---
    q_text_parts = []
    embedded_option_lines = []

    for ql in question_lines:
        t = re.sub(r'^>\s*', '', ql).strip()
        if not t:
            continue
        marker_num, remaining = detect_marker_at_start(t)
        if marker_num is not None:
            embedded_option_lines.append((marker_num, remaining))
        else:
            q_text_parts.append(t)

    raw_q_text = smart_join(q_text_parts)
    raw_q_text = strip_trailing_answer_marker(raw_q_text)
    raw_q_text = re.sub(r'-\s*보\s+기\s*', '보기 ', raw_q_text)
    raw_q_text = re.sub(r'-\s*보기\s+', '보기 ', raw_q_text)
    raw_q_text = raw_q_text.strip()
    if raw_q_text.startswith('- '):
        raw_q_text = raw_q_text[2:].strip()
    result['question_text'] = fix_spacing(raw_q_text)

    # --- Parse options ---
    entries = []  # list of (marker_num_or_none, text)

    for ol in option_lines:
        text = ol
        if text.startswith('- '):
            text = text[2:]
        text = text.strip()
        if not text:
            continue
        marker_num, remaining = detect_marker_at_start(text)
        entries.append((marker_num, remaining if marker_num else text))

    # Add embedded options from question blockquote
    for marker_num, text in embedded_option_lines:
        entries.insert(0 if marker_num == 1 else len(entries), (marker_num, text))

    # --- Handle duplicate markers ---
    marker_has_text = {}
    for idx, (marker, text) in enumerate(entries):
        if marker is not None:
            if marker not in marker_has_text:
                marker_has_text[marker] = []
            marker_has_text[marker].append((idx, bool(text.strip())))

    skip_indices = set()
    for mk, occurrences in marker_has_text.items():
        if len(occurrences) > 1:
            has_text_versions = [idx for idx, has_t in occurrences if has_t]
            bare_versions = [idx for idx, has_t in occurrences if not has_t]
            if has_text_versions:
                skip_indices.update(bare_versions)

    entries = [(m, t) for idx, (m, t) in enumerate(entries) if idx not in skip_indices]

    # Handle remaining duplicates by bumping
    seen_markers_set = set()
    fixed_entries = []
    for marker, text in entries:
        if marker is not None:
            if marker in seen_markers_set:
                new_marker = marker + 1
                while new_marker in seen_markers_set and new_marker <= 5:
                    new_marker += 1
                if new_marker <= 5:
                    marker = new_marker
            seen_markers_set.add(marker)
        fixed_entries.append((marker, text))
    entries = fixed_entries

    # --- Group entries: markers start new options ---
    # Orphaned lines before first marker → question continuation
    # Lines between markers → option continuation
    # Lines after last marker (no more markers coming) → check leak vs continuation
    parsed_options = {}
    current_marker = None
    current_parts = []
    leaked_lines = []  # explanation text leaked into options area
    orphaned_question_parts = []  # non-marker lines before first marker

    marker_positions = [i for i, (m, t) in enumerate(entries) if m is not None]
    first_marker_pos = marker_positions[0] if marker_positions else len(entries)

    for idx, (marker, text) in enumerate(entries):
        # Lines before first marker → question continuation
        if idx < first_marker_pos:
            orphaned_question_parts.append(text)
            continue

        if marker is not None:
            # Save previous option
            if current_marker is not None and current_parts:
                parsed_options[current_marker] = smart_join(current_parts)
            current_marker = marker
            current_parts = [text] if text else []
        else:
            # Non-marker line
            if current_marker is None:
                continue

            later_markers = [i for i in marker_positions if i > idx]

            if later_markers:
                # More markers coming → genuine continuation
                current_parts.append(text)
            else:
                # No more markers → leak or continuation?
                current_text_so_far = smart_join(current_parts) if current_parts else ''

                ends_with_sentence = bool(re.search(r'[.다!?]\s*$', current_text_so_far))
                is_short_complete = len(current_text_so_far) < 40 and not re.search(r'[에의을를와과로]$', current_text_so_far)
                is_much_longer = len(text) > len(current_text_so_far) * 1.5 and len(text) > 30

                if ends_with_sentence or is_short_complete or is_much_longer:
                    # Leaked explanation text → capture it
                    leaked_lines.append(text)
                else:
                    current_parts.append(text)

    # Save last option
    if current_marker is not None and current_parts:
        parsed_options[current_marker] = smart_join(current_parts)

    # Append orphaned question text
    if orphaned_question_parts:
        extra_q = smart_join(orphaned_question_parts)
        extra_q = fix_spacing(extra_q)
        if result['question_text']:
            result['question_text'] += '\n' + extra_q
        else:
            result['question_text'] = extra_q

    # Fix spacing in each option
    for k in list(parsed_options.keys()):
        parsed_options[k] = fix_spacing(parsed_options[k])

    # --- Parse answer block ---
    answer_num = None
    explanation_parts = []
    missing_options_from_answer = {}

    in_answer_content = False
    for al in answer_lines:
        t = re.sub(r'^>\s*', '', al).strip()

        if '[!answer]' in t:
            in_answer_content = True
            continue

        if not in_answer_content:
            continue

        # Check for answer line: **정답: X**
        ans_match = re.search(r'\*\*정답:\s*([①②③④⑤?➀➁➂➃ⓛ1-5])\s*\*\*', t)
        if ans_match:
            ans_char = ans_match.group(1)
            if ans_char == '?':
                answer_num = '?'
            elif ans_char in ALL_MARKERS:
                answer_num = ALL_MARKERS[ans_char]
            elif ans_char in '12345':
                answer_num = int(ans_char)
            else:
                answer_num = ans_char
            continue

        if not t:
            continue

        # Check if line starts with an option marker → might be a missing option
        opt_marker, opt_text = detect_marker_at_start(t)
        if opt_marker and opt_marker not in parsed_options:
            missing_options_from_answer[opt_marker] = opt_text
        elif opt_marker and opt_marker in parsed_options:
            explanation_parts.append(t)
        else:
            m2 = re.match(r'([①②③④➀➁➂➃ⓛ])\s*(.*)', t)
            if m2:
                mk = ALL_MARKERS.get(m2.group(1))
                txt = m2.group(2).strip()
                if mk and mk not in parsed_options:
                    missing_options_from_answer[mk] = txt
                else:
                    explanation_parts.append(t)
            else:
                explanation_parts.append(t)

    # Merge missing options from answer block
    for k, v in missing_options_from_answer.items():
        if k not in parsed_options:
            parsed_options[k] = fix_spacing(v)

    # Handle missing answer option
    if len(parsed_options) < 4 and answer_num and answer_num != '?' and answer_num not in parsed_options:
        if explanation_parts:
            first_line = explanation_parts[0]
            m = re.match(r'^([가-힣A-Za-z0-9·\-\s]{2,20}?)(?:은|는|의|이|을|를|에|와|과|로|으로)\s', first_line)
            if m:
                parsed_options[answer_num] = fix_spacing(m.group(1).strip())
            else:
                parsed_options[answer_num] = fix_spacing(first_line)
                explanation_parts = explanation_parts[1:]

    # --- Merge leaked lines with explanation ---
    # Leaked lines from options area + explanation from answer block
    if leaked_lines:
        leaked_text = smart_join(leaked_lines)
        if explanation_parts:
            # Check if leaked text continues into first explanation line (mid-word break)
            first_exp = explanation_parts[0]
            combined_first = smart_join([leaked_text, first_exp])
            full_parts = [combined_first] + explanation_parts[1:]
        else:
            full_parts = [leaked_text]
        explanation_text = smart_join(full_parts)
    else:
        explanation_text = smart_join(explanation_parts)

    # Normalize and clean explanation
    explanation_text = fix_spacing(explanation_text)
    explanation_text = normalize_special_chars(explanation_text)

    # Apply normalization to all text fields
    result['question_text'] = normalize_special_chars(result['question_text'])

    # Strip leaked answer marker from question text
    # After ? or sentence-ending . (고르시오. / 것은?) followed by single digit
    qt = result['question_text']
    # Pattern: "것은? ④" or "고르시오. ④" → strip the marker (now plain digit after normalize)
    qt = re.sub(r'([?.!])\s*[①②③④⑤➀➁➂➃ⓛ](?=\s|$)', r'\1', qt)
    # Strip leaked plain-digit answer after ? . ! when followed by any content
    qt = re.sub(r'([?.!])\s+[1-5](?=\s+[가-힣ㄱ-ㅎ(「<\[])', r'\1', qt)
    qt = re.sub(r'([?.!])\s+[1-5]\s*$', r'\1', qt)
    # Clean "보기 -" or "- 보기 -" PDF artifact
    qt = re.sub(r'\s*-?\s*보기\s*-\s*', '\n', qt)
    # Clean leading "- " or "○ " in question continuation
    qt = re.sub(r'\n\s*[-○]\s*', '\n', qt)
    qt = fix_spacing(qt.strip())
    result['question_text'] = qt

    for k in list(parsed_options.keys()):
        parsed_options[k] = normalize_special_chars(parsed_options[k])

    result['options'] = parsed_options
    result['answer'] = answer_num
    result['explanation'] = explanation_text

    return result


def parse_md_file(filepath, sec_num=0):
    """Parse an entire quiz MD file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')

    # Extract frontmatter
    frontmatter = ''
    body_start = 0

    if lines[0].strip() == '---':
        end_fm = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                end_fm = i
                break
        if end_fm > 0:
            frontmatter = '\n'.join(lines[0:end_fm+1])
            body_start = end_fm + 1

    # Extract header
    header_lines = []
    first_q_line = -1
    for i in range(body_start, len(lines)):
        if re.match(r'^###\s+Q\d+\.', lines[i].strip()):
            first_q_line = i
            break

    if first_q_line > body_start:
        header_lines = lines[body_start:first_q_line]

    # Split into question blocks
    question_blocks = []
    current_block = []

    for i in range(first_q_line, len(lines)):
        line = lines[i]
        stripped = line.strip()

        if re.match(r'^###\s+Q\d+\.', stripped):
            if current_block:
                question_blocks.append(current_block)
            current_block = [stripped]
        elif stripped.startswith('> [!summary]'):
            if current_block:
                question_blocks.append(current_block)
            current_block = []
            break
        elif stripped == '---':
            continue
        else:
            if current_block is not None:
                current_block.append(line)

    if current_block:
        question_blocks.append(current_block)

    # Parse each block
    questions = []
    for block in question_blocks:
        q = parse_question_block(block, sec_num)
        if q['q_num'] is not None:
            questions.append(q)

    return frontmatter, header_lines, questions


def build_clean_md(frontmatter, header_lines, questions, total_count):
    """Build clean MD content from parsed data."""
    parts = []

    if frontmatter:
        parts.append(frontmatter)

    header_text = '\n'.join(header_lines)
    header_text = re.sub(
        r'(# .+Quiz\s*)\(\d+문항\)',
        lambda m: f'{m.group(1)}({total_count}문항)',
        header_text
    )
    parts.append(header_text)

    for q in questions:
        q_parts = []
        q_parts.append(f'### Q{q["q_num"]}.')
        q_parts.append('')

        # Question text may have newlines (orphaned continuation)
        q_lines = q['question_text'].split('\n')
        for ql in q_lines:
            q_parts.append(f'> {ql}')
        q_parts.append('')

        # Options with plain number markers
        for i in range(1, 5):
            opt_text = q['options'].get(i, '')
            q_parts.append(f'- {i}. {opt_text}')

        q_parts.append('')

        # Answer as plain number
        ans_display = '?'
        if q['answer'] is not None and q['answer'] != '?':
            try:
                ans_display = str(int(q['answer']))
            except (ValueError, TypeError):
                ans_display = '?'

        q_parts.append('> [!answer]- 정답 보기')
        q_parts.append(f'> **정답: {ans_display}**')
        q_parts.append('> ')

        if q['explanation']:
            q_parts.append(f'> {q["explanation"]}')

        q_parts.append('')
        q_parts.append('---')
        q_parts.append('')

        parts.append('\n'.join(q_parts))

    parts.append('> [!summary]- 섹션 요약')
    parts.append(f'> 총 {total_count}문항 | 출처: 병원 공통시험 문제은행 (2026.01.27.)')
    parts.append('> 실제 시험에서 동일 문제 출제 — 반복 학습 필수')
    parts.append('')

    return '\n'.join(parts)


def main():
    all_questions_json = []
    sections_json = []
    total_questions = 0

    for sec_num, dir_name, quiz_filename in SECTIONS:
        filepath = os.path.join(VAULT, dir_name, quiz_filename)
        print(f"\n{'='*60}")
        print(f"Processing Section {sec_num}: {quiz_filename}")
        print(f"{'='*60}")

        if not os.path.exists(filepath):
            print(f"  WARNING: File not found: {filepath}")
            continue

        frontmatter, header_lines, questions = parse_md_file(filepath, sec_num)
        print(f"  Parsed {len(questions)} questions")

        # Validate
        for q in questions:
            missing = [i for i in range(1, 5) if i not in q['options'] or not q['options'].get(i, '').strip()]
            if missing:
                print(f"  Q{q['q_num']}: Missing/empty options {missing}")
            if q['answer'] is None:
                print(f"  Q{q['q_num']}: No answer found!")
            elif q['answer'] == '?':
                print(f"  Q{q['q_num']}: Answer is '?' (unknown)")

        section_name = quiz_filename.replace(' Quiz.md', '')
        sections_json.append({
            "id": sec_num,
            "name": section_name,
            "count": len(questions)
        })

        for q in questions:
            opts = []
            for i in range(1, 5):
                opts.append(q['options'].get(i, ''))

            ans = q['answer']
            if ans == '?' or ans is None:
                ans = 1  # fallback
            if isinstance(ans, str):
                ans = 1

            all_questions_json.append({
                "id": f"{sec_num}_{q['q_num']}",
                "s": sec_num,
                "q": q['q_num'],
                "text": q['question_text'],
                "opts": opts,
                "ans": ans
            })

        total_questions += len(questions)

        clean_md = build_clean_md(frontmatter, header_lines, questions, len(questions))
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(clean_md)
        print(f"  Wrote clean MD: {filepath}")

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Total questions parsed: {total_questions}")

    # Build and write JSON
    data = {"sections": sections_json, "questions": all_questions_json}
    json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    new_line = f'const DATA = {json_str};'

    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        html_lines = f.readlines()

    data_line_idx = None
    for i, line in enumerate(html_lines):
        if 'const DATA = {' in line:
            data_line_idx = i
            break

    if data_line_idx is None:
        print("ERROR: Could not find 'const DATA = {' in index.html!")
        return

    print(f"Found DATA line at line {data_line_idx + 1}")
    html_lines[data_line_idx] = new_line + '\n'

    with open(INDEX_HTML, 'w', encoding='utf-8') as f:
        f.writelines(html_lines)

    print(f"Updated index.html with {len(all_questions_json)} questions")

    # Final verification
    empty_count = sum(1 for q in all_questions_json for o in q['opts'] if not o.strip())
    print(f"Empty options remaining: {empty_count}")
    print("Done!")


if __name__ == '__main__':
    main()
