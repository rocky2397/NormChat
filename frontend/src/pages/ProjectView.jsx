import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  deleteDocument,
  getProject,
  listDocuments,
  listProjects,
  uploadDocument,
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

  async function handleUpload(file, onProgress) {
    await uploadDocument(projectId, file, onProgress)
    await refresh()
  }

  async function handleDeleteDocument(documentId) {
    if (!window.confirm('Dokument wirklich entfernen?')) return
    await deleteDocument(documentId)
    await refresh()
  }

  function handleOpenSource(source) {
    const { document_id: documentId, page_number: pageNumber, chunk_text: highlightText, filename } = source
    if (window.electronAPI) {
      window.electronAPI.openPdfWindow(documentId, pageNumber, highlightText, filename)
      return
    }
    // Fallback outside Electron (e.g. plain browser during dev): a normal
    // browser popup pointed at the same standalone viewer route.
    const search = new URLSearchParams({ page: String(pageNumber), text: highlightText, filename }).toString()
    window.open(`/documents/${documentId}/viewer?${search}`, '_blank', 'width=1000,height=1100')
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
