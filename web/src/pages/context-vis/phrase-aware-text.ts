export type CjkLanguage = "ja" | "ko" | "zh";

export interface PhraseChunk {
  readonly text: string;
  readonly keepTogether: boolean;
}

const MAX_PHRASE_CODE_POINTS = 6;
const SEGMENTERS: Readonly<Record<CjkLanguage, Intl.Segmenter>> = {
  ja: new Intl.Segmenter("ja", { granularity: "word" }),
  ko: new Intl.Segmenter("ko", { granularity: "word" }),
  zh: new Intl.Segmenter("zh", { granularity: "word" }),
};

function codePointCount(value: string): number {
  return [...value].length;
}

function groupWordRun(words: readonly string[]): PhraseChunk[] {
  const grouped: string[] = [];
  let end = words.length;
  while (end > 0) {
    let start = Math.max(0, end - 2);
    let text = words.slice(start, end).join("");
    while (
      start > 0
      && codePointCount(words[start - 1]) === 1
      && codePointCount(words[start - 1] + text) <= MAX_PHRASE_CODE_POINTS
    ) {
      start -= 1;
      text = words[start] + text;
    }
    grouped.unshift(text);
    end = start;
  }
  if (
    grouped.length > 1
    && codePointCount(grouped[0] + grouped[1]) <= MAX_PHRASE_CODE_POINTS
  ) {
    grouped.splice(0, 2, grouped[0] + grouped[1]);
  }
  return grouped.map((text) => ({ text, keepTogether: true }));
}

export function inferCjkLanguage(content: string): CjkLanguage | undefined {
  if (/[\p{Script=Hiragana}\p{Script=Katakana}]/u.test(content)) return "ja";
  if (/\p{Script=Hangul}/u.test(content)) return "ko";
  if (/\p{Script=Han}/u.test(content)) return "zh";
  return undefined;
}

export function phraseAwareChunks(
  content: string,
  language = inferCjkLanguage(content),
): readonly PhraseChunk[] {
  if (!language) return [{ text: content, keepTogether: false }];
  const chunks: PhraseChunk[] = [];
  let wordRun: string[] = [];
  const flushWords = (): void => {
    chunks.push(...groupWordRun(wordRun));
    wordRun = [];
  };
  for (const token of SEGMENTERS[language].segment(content)) {
    if (token.isWordLike === true) {
      wordRun.push(token.segment);
      continue;
    }
    flushWords();
    if (/^\s+$/u.test(token.segment) || chunks.length === 0) {
      chunks.push({ text: token.segment, keepTogether: false });
      continue;
    }
    const previous = chunks[chunks.length - 1];
    chunks[chunks.length - 1] = {
      text: previous.text + token.segment,
      keepTogether: previous.keepTogether,
    };
  }
  flushWords();
  return chunks;
}
