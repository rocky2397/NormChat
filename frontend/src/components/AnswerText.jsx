import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

// The model emits LaTeX wrapped in \[...\] (block) and \(...\) (inline),
// but remark-math only recognizes dollar delimiters — rewrite them before
// parsing. Bare formulas without any delimiter (e.g. "αcc") stay plain
// text rather than guessing.
const BLOCK_MATH_PATTERN = /\\\[([\s\S]+?)\\\]/g
const INLINE_MATH_PATTERN = /\\\(([\s\S]+?)\\\)/g

function normalizeMathDelimiters(text) {
  return text
    .replace(BLOCK_MATH_PATTERN, (_, expr) => `\n$$\n${expr}\n$$\n`)
    .replace(INLINE_MATH_PATTERN, (_, expr) => `$${expr}$`)
}

export default function AnswerText({ text }) {
  return (
    <div className="prose prose-sm prose-slate max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { errorColor: '#cc0000' }]]}
      >
        {normalizeMathDelimiters(text)}
      </ReactMarkdown>
    </div>
  )
}
