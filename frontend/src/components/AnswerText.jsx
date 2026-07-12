import { InlineMath, BlockMath } from 'react-katex'
import 'katex/dist/katex.min.css'

// Matches \[...\] (block) and \(...\) (inline) — the delimiters the model
// actually uses when it emits LaTeX. It doesn't always wrap formulas this
// way (sometimes it just writes a bare "αcc"), so only text inside a
// recognized delimiter pair is treated as math; everything else stays
// plain text rather than guessing.
const MATH_PATTERN = /\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)/g

function renderFallback(raw) {
  return <span>{raw}</span>
}

export default function AnswerText({ text }) {
  // MATH_PATTERN is a shared module-level regex (the `g` flag needs it to
  // be, to track position across .exec() calls within one run) — reset
  // defensively in case a previous call was interrupted before reaching
  // its natural (auto-resetting) null match.
  MATH_PATTERN.lastIndex = 0
  const parts = []
  let lastIndex = 0
  let match
  let key = 0

  while ((match = MATH_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<span key={key++}>{text.slice(lastIndex, match.index)}</span>)
    }

    const [full, blockMath, inlineMath] = match
    if (blockMath !== undefined) {
      parts.push(
        <BlockMath
          key={key++}
          math={blockMath}
          errorColor="#cc0000"
          renderError={() => renderFallback(full)}
        />,
      )
    } else {
      parts.push(
        <InlineMath
          key={key++}
          math={inlineMath}
          errorColor="#cc0000"
          renderError={() => renderFallback(full)}
        />,
      )
    }
    lastIndex = MATH_PATTERN.lastIndex
  }

  if (lastIndex < text.length) {
    parts.push(<span key={key++}>{text.slice(lastIndex)}</span>)
  }

  return <p className="whitespace-pre-wrap">{parts}</p>
}
