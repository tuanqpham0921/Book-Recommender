import { useState, useEffect, lazy, Suspense } from 'react'
import { MessageCircle } from 'lucide-react'
import api from '@/api'
import { IssueReportModal } from '@/components/chatbot/ChatFeedback'

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
function ChatRunRow({ run, sessionId }) {
    const [expanded, setExpanded] = useState(false)
    const [feedback, setFeedback] = useState(null)
    const [showFeedbackModal, setShowFeedbackModal] = useState(false)
    const diagram = run.orchestration?.output?.diagram
    const parseResult = run.orchestration?.output?.parse_result
    const errorDetail = run.orchestration?.runtime_error

    async function loadFeedback() {
        try {
            const data = await api.getFeedback(run.chat_id)
            setFeedback(data.feedback || [])
        } catch (err) {
            console.error('Failed to load feedback:', err)
            setFeedback([])
        }
    }

    // Load once on first expand; re-queried after the report modal closes
    // (below) so a just-submitted entry shows up without a full page refresh.
    useEffect(() => {
        if (!expanded || feedback !== null) return
        loadFeedback()
    }, [expanded, feedback, run.chat_id])

    return (
        <div className="border border-gray-200 rounded-lg bg-white">
            <div
                role="button"
                tabIndex={0}
                onClick={() => setExpanded(prev => !prev)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(prev => !prev) } }}
                className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors cursor-pointer"
            >
                <span className="text-gray-400 text-xs w-4">{expanded ? '▼' : '▶'}</span>
                <StatusBadge ok={run.ok} />
                {run.runtime_error && (
                    <span
                        title={errorDetail?.message}
                        className="px-2 py-0.5 rounded-full text-xs bg-red-50 text-red-600 border border-red-200 whitespace-nowrap"
                    >
                        {run.runtime_error}
                    </span>
                )}
                <span className="flex-1 truncate text-sm text-gray-800">
                    {run.user_message || <em className="text-gray-400">no message</em>}
                </span>
                <span className="text-sm"><FeedbackBadge liked={run.liked} /></span>
                <span className="text-xs text-gray-400 whitespace-nowrap">
                    {run.created_at ? new Date(run.created_at).toLocaleString() : ''}
                </span>
                <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setShowFeedbackModal(true) }}
                    title="Report on this run"
                    className="p-1 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
                >
                    <MessageCircle size={16} />
                </button>
            </div>

            <IssueReportModal
                chatId={run.chat_id}
                sessionId={sessionId}
                isOpen={showFeedbackModal}
                onClose={() => { setShowFeedbackModal(false); loadFeedback() }}
                review
            />

            {expanded && (
                <div className="px-4 pb-4 border-t border-gray-100 text-sm">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 my-3 text-xs text-gray-600">
                        <div><span className="font-semibold">chat_id:</span> {run.chat_id}</div>
                        <div><span className="font-semibold">session:</span> {run.session_id}</div>
                        <div><span className="font-semibold">duration:</span> {run.duration_s?.toFixed?.(2) ?? '—'}s</div>
                        <div><span className="font-semibold">tokens:</span> {run.total_tokens ?? '—'}</div>
                    </div>

                    {feedback?.length > 0 && (
                        <div className="mb-3 flex flex-col gap-2">
                            {feedback.map((entry, i) => (
                                <div key={i} className="p-2 bg-yellow-50 border border-yellow-200 rounded">
                                    <div className="flex items-center gap-2 mb-1">
                                        {entry.title && (
                                            <span
                                                className={`px-2 py-0.5 rounded-full text-xs ${
                                                    entry.positive
                                                        ? 'bg-green-100 text-green-700'
                                                        : 'bg-red-100 text-red-700'
                                                }`}
                                            >
                                                {entry.title}
                                            </span>
                                        )}
                                        {entry.created_at && (
                                            <span className="text-[11px] text-gray-400">
                                                {new Date(entry.created_at).toLocaleString()}
                                            </span>
                                        )}
                                    </div>
                                    <div className="text-gray-700">{entry.message}</div>
                                </div>
                            ))}
                        </div>
                    )}

                    {errorDetail && (
                        <details className="mb-3">
                            <summary className="cursor-pointer text-red-600 font-semibold">
                                {run.runtime_error}: {errorDetail.message}
                            </summary>
                            <pre className="mt-1 p-2 bg-red-50 border border-red-100 rounded overflow-x-auto text-xs max-h-96 overflow-y-auto">
                                {errorDetail.traceback}
                            </pre>
                        </details>
                    )}

                    {diagram && (
                        <details className="mb-3">
                            <summary className="cursor-pointer text-gray-600 font-semibold">Task plan diagram</summary>
                            <Suspense fallback={<div className="text-gray-400 p-2">Loading diagram...</div>}>
                                <div className="border border-gray-100 rounded p-2 mt-1">
                                    <MermaidDiagram chart={diagram} className="w-full" />
                                </div>
                            </Suspense>
                        </details>
                    )}

                    {parseResult && (
                        <details className="mb-3">
                            <summary className="cursor-pointer text-gray-600 font-semibold">System goals</summary>
                            <div className="mt-2 flex flex-col gap-3">
                                {parseResult.reasoning && (
                                    <p className="text-xs text-gray-500 italic">{parseResult.reasoning}</p>
                                )}

                                {parseResult.accepted_goals?.length > 0 && (
                                    <div>
                                        <div className="text-xs font-semibold text-gray-500 uppercase mb-1">Accepted</div>
                                        <div className="flex flex-col gap-1">
                                            {parseResult.accepted_goals.map(goal => (
                                                <div key={goal._id} className="flex items-center gap-2 p-2 bg-green-50 border border-green-100 rounded text-xs">
                                                    <span className="px-2 py-0.5 rounded-full bg-green-100 text-green-700 whitespace-nowrap">
                                                        {goal.target_node_type}
                                                    </span>
                                                    <span className="flex-1 text-gray-700">{goal.description}</span>
                                                    <span className="text-gray-400 whitespace-nowrap">{Math.round(goal.confidence * 100)}%</span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {parseResult.refused_goals?.length > 0 && (
                                    <div>
                                        <div className="text-xs font-semibold text-gray-500 uppercase mb-1">Refused</div>
                                        <div className="flex flex-col gap-1">
                                            {parseResult.refused_goals.map(goal => (
                                                <div key={goal._id} className="p-2 bg-red-50 border border-red-100 rounded text-xs">
                                                    <div className="flex items-center gap-2">
                                                        <span className="px-2 py-0.5 rounded-full bg-red-100 text-red-700 whitespace-nowrap">
                                                            {goal.target_node_type}
                                                        </span>
                                                        <span className="flex-1 text-gray-700">{goal.description}</span>
                                                        <span className="text-gray-400 whitespace-nowrap">{Math.round(goal.confidence * 100)}%</span>
                                                    </div>
                                                    {goal._refusal_reasons?.length > 0 && (
                                                        <div className="mt-1 text-gray-500 italic">{goal._refusal_reasons.join('; ')}</div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {!parseResult.accepted_goals?.length && !parseResult.refused_goals?.length && (
                                    <div className="text-xs text-gray-400 italic">No goals recorded.</div>
                                )}
                            </div>
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
    // Own session, separate from any live chat session — feedback filed
    // from this page is tagged review=true and shouldn't be grouped under
    // whatever session a visitor's actual chat conversation is using.
    const [sessionId, setSessionId] = useState(null)

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
        api.createSession()
            .then(({ id }) => setSessionId(id))
            .catch(err => console.error('Failed to create session:', err))
    }, [])

    return (
        <div className="min-h-full bg-[var(--bg-secondary)]">
            <div className="max-w-4xl mx-auto px-4 py-4">
                <div className="flex items-center justify-between mb-4">
                    <span className="text-sm text-gray-500">
                        {isLoading ? 'Loading runs…' : `${runs.length} chat run${runs.length === 1 ? '' : 's'}`}
                    </span>
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
                    {runs.map(run => <ChatRunRow key={run.chat_id} run={run} sessionId={sessionId} />)}
                </div>
            </div>
        </div>
    )
}

export default ChatReviewPage
