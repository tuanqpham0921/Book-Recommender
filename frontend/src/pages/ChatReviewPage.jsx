import { useState, useEffect, lazy, Suspense } from 'react'
import api from '@/api'

const MermaidDiagram = lazy(() => import('@/components/MermaidDiagram'))

function FeedbackBadge({ liked }) {
    if (liked === true) return <span className="text-green-600">👍 liked</span>
    if (liked === false) return <span className="text-red-600">👎 disliked</span>
    return <span className="text-gray-400">—</span>
}

function StatusBadge({ ok }) {
    if (ok === true) return <span className="px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700">ok</span>
    if (ok === false) return <span className="px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700">failed</span>
    return <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-500">unknown</span>
}

// One chat run row: summary line + expandable detail (feedback, mermaid, full
// orchestration envelope).
function ChatRunRow({ run }) {
    const [expanded, setExpanded] = useState(false)

    return (
        <div className="border border-gray-200 rounded-lg bg-white">
            <button
                type="button"
                onClick={() => setExpanded(prev => !prev)}
                className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
            >
                <span className="text-gray-400 text-xs w-4">{expanded ? '▼' : '▶'}</span>
                <StatusBadge ok={run.ok} />
                <span className="flex-1 truncate text-sm text-gray-800">
                    {run.user_message || <em className="text-gray-400">no message</em>}
                </span>
                <span className="text-sm"><FeedbackBadge liked={run.liked} /></span>
                {run.comment && <span title={run.comment}>💬</span>}
                <span className="text-xs text-gray-400 whitespace-nowrap">
                    {run.created_at ? new Date(run.created_at).toLocaleString() : ''}
                </span>
            </button>

            {expanded && (
                <div className="px-4 pb-4 border-t border-gray-100 text-sm">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 my-3 text-xs text-gray-600">
                        <div><span className="font-semibold">chat_id:</span> {run.chat_id}</div>
                        <div><span className="font-semibold">session:</span> {run.session_id}</div>
                        <div><span className="font-semibold">duration:</span> {run.duration_s?.toFixed?.(2) ?? '—'}s</div>
                        <div><span className="font-semibold">tokens:</span> {run.total_tokens ?? '—'}</div>
                    </div>

                    {run.comment && (
                        <div className="mb-3 p-2 bg-yellow-50 border border-yellow-200 rounded text-gray-700">
                            <span className="font-semibold">Comment:</span> {run.comment}
                        </div>
                    )}

                    {run.mermaid && (
                        <details className="mb-3">
                            <summary className="cursor-pointer text-gray-600 font-semibold">Task plan diagram</summary>
                            <Suspense fallback={<div className="text-gray-400 p-2">Loading diagram...</div>}>
                                <div className="border border-gray-100 rounded p-2 mt-1">
                                    <MermaidDiagram chart={run.mermaid} className="w-full" />
                                </div>
                            </Suspense>
                        </details>
                    )}

                    <details>
                        <summary className="cursor-pointer text-gray-600 font-semibold">Orchestration envelope</summary>
                        <pre className="mt-1 p-2 bg-gray-50 border border-gray-100 rounded overflow-x-auto text-xs max-h-96 overflow-y-auto">
                            {JSON.stringify(run.orchestration, null, 2)}
                        </pre>
                    </details>
                </div>
            )}
        </div>
    )
}

// Internal review page: lists every recorded chat run, newest first.
function ChatReviewPage() {
    const [runs, setRuns] = useState([])
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState(null)

    async function loadRuns() {
        setIsLoading(true)
        setError(null)
        try {
            const data = await api.getChatRuns()
            setRuns(data.runs || [])
        } catch (err) {
            console.error('Failed to load chat runs:', err)
            setError('Failed to load chat runs — is the backend running?')
        } finally {
            setIsLoading(false)
        }
    }

    useEffect(() => {
        loadRuns()
    }, [])

    return (
        <div className="min-h-screen bg-[var(--bg-secondary)]">
            <div className="max-w-4xl mx-auto px-4 py-8">
                <div className="flex items-center justify-between mb-6">
                    <h1 className="text-2xl font-bold text-gray-800">Chat Run Review</h1>
                    <button
                        type="button"
                        onClick={loadRuns}
                        disabled={isLoading}
                        className="px-3 py-1.5 text-sm rounded-md bg-gray-800 text-white disabled:opacity-40 hover:bg-gray-700 transition-colors"
                    >
                        {isLoading ? 'Loading...' : 'Refresh'}
                    </button>
                </div>

                {error && <div className="text-red-500 italic mb-4">{error}</div>}

                {!isLoading && !error && runs.length === 0 && (
                    <div className="text-gray-400 italic">No chat runs recorded yet.</div>
                )}

                <div className="flex flex-col gap-2">
                    {runs.map(run => <ChatRunRow key={run.chat_id} run={run} />)}
                </div>
            </div>
        </div>
    )
}

export default ChatReviewPage
