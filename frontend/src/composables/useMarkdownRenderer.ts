import { ref, computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'
import type { SourceCitation } from '../types/chat'

export function useMarkdownRenderer() {
  const renderer = new marked.Renderer()

  renderer.code = ({ text, lang }) => {
    const validLang = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
    const highlighted = hljs.highlight(text, { language: validLang }).value
    return `<pre class="code-block"><div class="code-header"><span class="code-lang">${validLang}</span><button class="code-copy-btn" onclick="navigator.clipboard.writeText(this.closest('pre').querySelector('code').textContent)">复制</button></div><code class="hljs ${validLang}">${highlighted}</code></pre>`
  }

  marked.setOptions({ renderer, breaks: true, gfm: true })

  let renderTimer: ReturnType<typeof setTimeout> | null = null
  const renderKey = ref(0)

  const triggerRender = () => {
    if (renderTimer) return
    renderTimer = setTimeout(() => {
      renderKey.value++
      renderTimer = null
    }, 50)
  }

  const renderMarkdown = (content: string) => {
    void renderKey.value
    if (!content) return ''
    let html = DOMPurify.sanitize(marked.parse(content) as string, { ADD_ATTR: ["data-cite-index"] })
    html = html.replace(/\[来源(\d+)\]/g, '<span class="cite-inline" data-cite-index="$1">来源$1</span>')
    return html
  }

  const activeCite = ref<{ source: SourceCitation; rect: DOMRect } | null>(null)

  const handleCiteClick = (e: MouseEvent, messages: { sources?: SourceCitation[] }[]) => {
    const target = (e.target as HTMLElement).closest('.cite-inline') as HTMLElement | null
    if (!target) return
    const citeIndex = parseInt(target.dataset.citeIndex || '0', 10) - 1
    const msgEl = target.closest('.msg') as HTMLElement | null
    if (!msgEl) return
    const msgIndex = msgEl.dataset.msgIndex
      ? parseInt(msgEl.dataset.msgIndex, 10)
      : Array.from(msgEl.parentElement!.children).indexOf(msgEl)
    if (msgIndex < 0 || msgIndex >= messages.length) return
    const msg = messages[msgIndex]
    if (!msg?.sources?.length) return
    const source = msg.sources[citeIndex] || msg.sources[0]
    activeCite.value = { source, rect: target.getBoundingClientRect() }
  }

  const closeCitePopover = () => { activeCite.value = null }

  const citePopoverStyle = computed(() => {
    if (!activeCite.value) return {}
    const r = activeCite.value.rect
    const top = Math.min(r.bottom + 8, window.innerHeight - 320)
    const left = Math.max(16, Math.min(r.left, window.innerWidth - 360))
    return { top: `${top}px`, left: `${left}px` }
  })

  return {
    renderKey,
    triggerRender,
    renderMarkdown,
    activeCite,
    handleCiteClick,
    closeCitePopover,
    citePopoverStyle,
  }
}
