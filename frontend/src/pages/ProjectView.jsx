import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  deleteDocument,
  getProject,
  listDocuments,
  listProjects,
  uploadDocuments,
} from '../api/client'
import ChatPanel from '../components/ChatPanel'
import DocumentUpload from '../components/DocumentUpload'
import ProjectSidebar from '../components/ProjectSidebar'

export default function ProjectView() {
  const { projectId } = useParams()
  const [project, setProject] = useState(null)
  const [projects, setProjects] = useState([])
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const pdfPopupRef = useRef(null)
  const pdfPopupReadyRef = useRef(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [projectData, projectList, documentList] = await Promise.all([
        getProject(projectId),
        listProjects(),
        listDocuments(projectId),
      ])
      setProject(projectData)
      setProjects(projectList)
      setDocuments(documentList)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    function handleMessage(event) {
      if (event.origin !== window.location.origin) return
      if (event.data !== 'normchat-viewer-ready' || event.source !== pdfPopupRef.current) return
      pdfPopupReadyRef.current = true
    }
    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [])

  async function handleUpload(files, onProgress) {
    await uploadDocuments(projectId, files, onProgress)
    await refresh()
  }

  async function handleDeleteDocument(documentId) {
    if (!window.confirm('Dokument wirklich entfernen?')) return
    await deleteDocument(documentId)
    await refresh()
  }

  function handleOpenSource(sources, initialIndex) {
    const payload = { sources, initialIndex }
    if (window.electronAPI) {
      window.electronAPI.openPdfWindow(payload)
      return
    }
    // Fallback outside Electron (e.g. plain browser during dev): reuse one
    // named popup window (browsers route repeat window.open calls with the
    // same name to the existing window) and sync its content via
    // postMessage — the payload is too large for a URL/query string.
    const isFreshPopup = !pdfPopupRef.current || pdfPopupRef.current.closed
    const popup = window.open('/viewer', 'normchat-pdf-viewer', 'width=1000,height=1100')
    if (!popup) return
    if (isFreshPopup) pdfPopupReadyRef.current = false
    pdfPopupRef.current = popup
    popup.focus()

    let attemptsLeft = 40
    const trySend = () => {
      if (pdfPopupReadyRef.current) {
        popup.postMessage({ type: 'update-sources', payload }, window.location.origin)
      } else if (attemptsLeft-- > 0) {
        setTimeout(trySend, 50)
      }
    }
    trySend()
  }

  if (loading && !project) {
    return <div className="p-8 text-sm text-slate-500">Projekt wird geladen…</div>
  }

  if (!project) {
    return <div className="p-8 text-sm text-red-600">Projekt nicht gefunden.</div>
  }

  return (
    <div className="min-h-screen bg-slate-100 p-4 lg:p-6">
      <div className="mx-auto grid h-[calc(100vh-2rem)] max-w-[1000px] gap-4 lg:grid-cols-[280px_1fr]">
        <ProjectSidebar
          projects={projects}
          currentProjectId={projectId}
          documents={documents}
          onDeleteDocument={handleDeleteDocument}
        />

        <div className="flex min-h-0 flex-col gap-4">
          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-3">
              <h1 className="text-xl font-semibold text-slate-900">{project.name}</h1>
              {project.bundesland && (
                <p className="text-sm text-slate-500">{project.bundesland}</p>
              )}
            </div>
            <DocumentUpload onUpload={handleUpload} />
          </section>

          <div className="min-h-0 flex-1">
            <ChatPanel
              projectId={projectId}
              onOpenSource={handleOpenSource}
              disabled={!documents.length}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
