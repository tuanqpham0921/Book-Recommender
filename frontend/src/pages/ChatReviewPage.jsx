import { useState, useEffect, lazy, Suspense } from 'react'
import { MessageCircle, ThumbsUp, ThumbsDown, ChevronDown } from 'lucide-react'
import api from '@/api'
import { IssueReportModal } from '@/components/chatbot/ChatFeedback'
import Button from '@/design-system/Button'
import IconButton from '@/design-system/IconButton'
import Badge from '@/design-system/Badge'
import Dropdown from '@/design-system/Dropdown'
import DropdownItem from '@/design-system/DropdownItem'
import Emoji from '@/design-system/Emoji'

const MermaidDiagram = lazy(() => import('@/components/MermaidDiagram'))

// Combines the end user's own reaction (chat_runs.liked) with reviewer
// signals from the feedback table (reviewer_liked/reviewer_disliked/
// has_report, embedded per-run by the backend) into one glanceable badge —
// dislikes take priority since those most need review attention.
function FeedbackBadge({ run }) {
    const disliked = run.liked === false || run.reviewer_disliked
    const liked = run.liked === true || run.reviewer_liked
    if (disliked) return <Badge tone="negative" title="Disliked"><Emoji>👎</Emoji> disliked</Badge>
    if (liked) return <Badge tone="positive" title="Liked"><Emoji>👍</Emoji> liked</Badge>
    if (run.has_report) return <Badge tone="warning" title="Has a written report"><Emoji>📝</Emoji> report</Badge>
    return <Badge tone="neutral">— unreviewed</Badge>
}

// Any liked/disliked/reported signal, from either chat_runs.liked or the
// feedback table — used to sort already-reviewed runs out of the way.
function isReviewed(run) {
    return run.liked === true || run.liked === false
        || run.reviewer_liked || run.reviewer_disliked || run.has_report
}

function StatusBadge({ ok }) {
    if (ok === true) return <Badge tone="positive">ok</Badge>
    if (ok === false) return <Badge tone="negative">failed</Badge>
    return <Badge tone="neutral">unknown</Badge>
}

// One chat run row: summary line + expandable detail (feedback, mermaid, full
// planner/tasks envelopes).
function ChatRunRow({ run, sessionId }) {
    const [expanded, setExpanded] = useState(false)
    const [feedback, setFeedback] = useState(null)
    const [showFeedbackModal, setShowFeedbackModal] = useState(false)
    const [isSavingReaction, setIsSavingReaction] = useState(false)
    const diagram = run.planner?.output?.diagram
    const parseResult = run.planner?.output?.parse_result
    const errorDetail = run.planner?.runtime_error

    // This reviewer session's own like/dislike on this run — independent of
    // run.liked (the original end-user's reaction) and of any other
    // reviewer session. One row per (chat_id, session_id), so at most one
    // match here.
    const reviewerReaction = feedback?.find(
        (entry) => entry.session_id === sessionId && entry.liked !== null && entry.liked !== undefined
    )?.liked ?? null

    // Pure reaction rows (title/message/positive all null) are already
    // reflected by the thumbs buttons above — only show written reports here.
    const writtenFeedback = feedback?.filter((entry) => entry.message) ?? []

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

    async function handleReviewerReaction(liked) {
        if (isSavingReaction || reviewerReaction === liked || !sessionId) return
        setIsSavingReaction(true)
        try {
            await api.setReviewerReaction(run.chat_id, sessionId, liked)
            await loadFeedback()
        } catch (err) {
            console.error('Failed to save reviewer reaction:', err)
        } finally {
            setIsSavingReaction(false)
        }
    }

    return (
        <div className="border border-[var(--border-light)] rounded-lg bg-[var(--bg-primary)]">
            <div
                role="button"
                tabIndex={0}
                onClick={() => setExpanded(prev => !prev)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(prev => !prev) } }}
                className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-[var(--bg-secondary)] transition-colors cursor-pointer"
            >
                <span className="text-[var(--text-muted)] text-xs w-4 mt-0.5">{expanded ? '▼' : '▶'}</span>
                <span className="mt-0.5"><StatusBadge ok={run.ok} /></span>
                {run.runtime_error && (
                    <Badge tone="negative" title={errorDetail?.message} className="mt-0.5 border border-[var(--accent-negative-border)] whitespace-nowrap">
                        {run.runtime_error}
                    </Badge>
                )}
                <span className="flex-1 whitespace-pre-wrap break-words text-sm text-[var(--text-active)] mt-1">
                    {run.user_message || <em className="text-[var(--text-muted)]">no message</em>}
                </span>
                <span className="text-sm mt-0.5"><FeedbackBadge run={run} /></span>
                <span className="text-xs text-[var(--text-muted)] whitespace-nowrap mt-1">
                    {run.created_at ? new Date(run.created_at).toLocaleString() : ''}
                </span>
            </div>

            <IssueReportModal
                chatId={run.chat_id}
                sessionId={sessionId}
                isOpen={showFeedbackModal}
                onClose={() => { setShowFeedbackModal(false); loadFeedback() }}
                review
            />

            {expanded && (
                <div className="px-4 pb-4 border-t border-[var(--border-light)] text-sm">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 my-3 text-xs text-[var(--text-hover)]">
                        <div><span className="font-semibold">chat_id:</span> {run.chat_id}</div>
                        <div><span className="font-semibold">session:</span> {run.session_id}</div>
                        <div><span className="font-semibold">duration:</span> {run.duration_s?.toFixed?.(2) ?? '—'}s</div>
                        <div><span className="font-semibold">tokens:</span> {run.total_tokens ?? '—'}</div>
                    </div>

                    <div className="flex items-center gap-1 mb-3">
                        <span className="text-xs text-[var(--text-inactive)] mr-1">Your reaction (this reviewer session):</span>
                        <IconButton
                            onClick={() => handleReviewerReaction(true)}
                            disabled={isSavingReaction || !sessionId}
                            title="I like this response"
                            tone="positive"
                            active={reviewerReaction === true}
                        >
                            <ThumbsUp size={14} />
                        </IconButton>
                        <IconButton
                            onClick={() => handleReviewerReaction(false)}
                            disabled={isSavingReaction || !sessionId}
                            title="I dislike this response"
                            tone="negative"
                            active={reviewerReaction === false}
                        >
                            <ThumbsDown size={14} />
                        </IconButton>
                        <IconButton
                            onClick={() => setShowFeedbackModal(true)}
                            title="Report on this run"
                        >
                            <MessageCircle size={16} />
                        </IconButton>
                    </div>

                    {writtenFeedback.length > 0 && (
                        <details className="mb-3">
                            <summary className="cursor-pointer text-[var(--text-hover)] font-semibold">
                                Reports ({writtenFeedback.length})
                            </summary>
                            <div className="mt-2 max-h-64 overflow-y-auto flex flex-col gap-2 pr-1">
                                {writtenFeedback.map((entry, i) => (
                                    <div key={i} className="p-2 bg-[var(--accent-warning-bg)] border border-[var(--accent-warning-border)] rounded">
                                        <div className="flex items-center gap-2 mb-1">
                                            {entry.title && (
                                                <Badge tone={entry.positive ? 'positive' : 'negative'}>
                                                    {entry.title}
                                                </Badge>
                                            )}
                                            {entry.created_at && (
                                                <span className="text-[11px] text-[var(--text-muted)]">
                                                    {new Date(entry.created_at).toLocaleString()}
                                                </span>
                                            )}
                                            {entry.review && (
                                                <span className="text-[11px] text-[var(--text-muted)]">
                                                    {'(reviewer)'}
                                                </span>
                                            )}
                                        </div>
                                        <div className="text-[var(--text-hover)]">{entry.message}</div>
                                    </div>
                                ))}
                            </div>
                        </details>
                    )}

                    {errorDetail && (
                        <details className="mb-3">
                            <summary className="cursor-pointer text-[var(--accent-negative)] font-semibold">
                                {run.runtime_error}: {errorDetail.message}
                            </summary>
                            <pre className="mt-1 p-2 bg-[var(--accent-negative-bg)] border border-[var(--accent-negative-border)] rounded overflow-x-auto text-xs max-h-96 overflow-y-auto">
                                {errorDetail.traceback}
                            </pre>
                        </details>
                    )}

                    {diagram && (
                        <details className="mb-3">
                            <summary className="cursor-pointer text-[var(--text-hover)] font-semibold">Task plan diagram</summary>
                            <Suspense fallback={<div className="text-[var(--text-muted)] p-2">Loading diagram...</div>}>
                                <div className="border border-[var(--border-light)] rounded p-2 mt-1">
                                    <MermaidDiagram chart={diagram} className="w-full" />
                                </div>
                            </Suspense>
                        </details>
                    )}

                    {parseResult && (
                        <details className="mb-3">
                            <summary className="cursor-pointer text-[var(--text-hover)] font-semibold">System goals</summary>
                            <div className="mt-2 flex flex-col gap-3">
                                {parseResult.reasoning && (
                                    <p className="text-xs text-[var(--text-inactive)] italic">{parseResult.reasoning}</p>
                                )}

                                {parseResult.accepted_goals?.length > 0 && (
                                    <div>
                                        <div className="text-xs font-semibold text-[var(--text-inactive)] uppercase mb-1">Accepted</div>
                                        <div className="flex flex-col gap-1">
                                            {parseResult.accepted_goals.map(goal => (
                                                <div key={goal._id} className="flex items-center gap-2 p-2 bg-[var(--accent-positive-bg)] border border-[var(--accent-positive-border)] rounded text-xs">
                                                    <Badge tone="positive" className="whitespace-nowrap">
                                                        {goal.target_node_type}
                                                    </Badge>
                                                    <span className="flex-1 text-[var(--text-hover)]">{goal.description}</span>
                                                    <span className="text-[var(--text-muted)] whitespace-nowrap">{Math.round(goal.confidence * 100)}%</span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {parseResult.refused_goals?.length > 0 && (
                                    <div>
                                        <div className="text-xs font-semibold text-[var(--text-inactive)] uppercase mb-1">Refused</div>
                                        <div className="flex flex-col gap-1">
                                            {parseResult.refused_goals.map(goal => (
                                                <div key={goal._id} className="p-2 bg-[var(--accent-negative-bg)] border border-[var(--accent-negative-border)] rounded text-xs">
                                                    <div className="flex items-center gap-2">
                                                        <Badge tone="negative" className="whitespace-nowrap">
                                                            {goal.target_node_type}
                                                        </Badge>
                                                        <span className="flex-1 text-[var(--text-hover)]">{goal.description}</span>
                                                        <span className="text-[var(--text-muted)] whitespace-nowrap">{Math.round(goal.confidence * 100)}%</span>
                                                    </div>
                                                    {goal._refusal_reasons?.length > 0 && (
                                                        <div className="mt-1 text-[var(--text-inactive)] italic">{goal._refusal_reasons.join('; ')}</div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {!parseResult.accepted_goals?.length && !parseResult.refused_goals?.length && (
                                    <div className="text-xs text-[var(--text-muted)] italic">No goals recorded.</div>
                                )}
                            </div>
                        </details>
                    )}

                    <details>
                        <summary className="cursor-pointer text-[var(--text-hover)] font-semibold">Planner envelope</summary>
                        <pre className="mt-1 p-2 bg-[var(--bg-secondary)] border border-[var(--border-light)] rounded overflow-x-auto text-xs max-h-96 overflow-y-auto">
                            {JSON.stringify(run.planner, null, 2)}
                        </pre>
                    </details>

                    {run.tasks && (
                        <details>
                            <summary className="cursor-pointer text-[var(--text-hover)] font-semibold">Tasks envelope</summary>
                            <pre className="mt-1 p-2 bg-[var(--bg-secondary)] border border-[var(--border-light)] rounded overflow-x-auto text-xs max-h-96 overflow-y-auto">
                                {JSON.stringify(run.tasks, null, 2)}
                            </pre>
                        </details>
                    )}
                </div>
            )}
        </div>
    )
}

const SESSION_FILTERS = [
    { value: 'all', label: 'All sessions' },
    { value: 'tests', label: 'Tests' },
]

// Internal review page: lists every recorded chat run, newest first.
function ChatReviewPage() {
    const [runs, setRuns] = useState([])
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState(null)
    const [sessionFilter, setSessionFilter] = useState('all')
    // When on, unreviewed runs (no liked/disliked/report signal from either
    // chat_runs or the feedback table) sort to the top — applies on top of
    // whichever session filter is active. Off by default: plain newest-first.
    const [prioritizeReview, setPrioritizeReview] = useState(false)
    // Own session, separate from any live chat session — feedback filed
    // from this page is tagged review=true and shouldn't be grouped under
    // whatever session a visitor's actual chat conversation is using.
    const [sessionId, setSessionId] = useState(null)

    async function loadRuns(filter = sessionFilter) {
        setIsLoading(true)
        setError(null)
        try {
            const data = await api.getChatRuns(200, 0, filter)
            setRuns(data.runs || [])
        } catch (err) {
            console.error('Failed to load chat runs:', err)
            setError('Failed to load chat runs — is the backend running?')
        } finally {
            setIsLoading(false)
        }
    }

    useEffect(() => {
        api.createSession()
            .then(({ id }) => setSessionId(id))
            .catch(err => console.error('Failed to create session:', err))
    }, [])

    // Query the backend on mount and whenever the filter changes.
    useEffect(() => {
        loadRuns(sessionFilter)
    }, [sessionFilter])

    // Always newest-first; when prioritizeReview is on, unreviewed runs
    // additionally float above reviewed ones (within each group still
    // newest-first).
    const sortedRuns = [...runs].sort((a, b) => {
        if (prioritizeReview) {
            const aDone = isReviewed(a)
            const bDone = isReviewed(b)
            if (aDone !== bDone) return aDone ? 1 : -1
        }
        return new Date(b.created_at) - new Date(a.created_at)
    })

    const activeFilter = SESSION_FILTERS.find(f => f.value === sessionFilter) ?? SESSION_FILTERS[0]

    return (
        <div className="min-h-full bg-[var(--bg-secondary)]">
            <div className="max-w-4xl mx-auto px-4 py-4">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                        <span className="text-sm text-[var(--text-inactive)]">
                            {isLoading ? 'Loading runs…' : `${sortedRuns.length} chat run${sortedRuns.length === 1 ? '' : 's'}`}
                        </span>

                        <Dropdown
                            panelClassName="w-40"
                            trigger={({ toggle }) => (
                                <Button variant="secondary" onClick={toggle} className="gap-1">
                                    {activeFilter.label}
                                    <ChevronDown size={14} />
                                </Button>
                            )}
                        >
                            {({ close }) => SESSION_FILTERS.map(({ value, label }) => (
                                <DropdownItem
                                    key={value}
                                    selected={value === sessionFilter}
                                    onClick={() => { setSessionFilter(value); close() }}
                                >
                                    {label}
                                </DropdownItem>
                            ))}
                        </Dropdown>

                        <Button
                            onClick={() => setPrioritizeReview(prev => !prev)}
                            title="Sort unreviewed runs to the top (still newest-first within each group)"
                            active={prioritizeReview}
                        >
                            {prioritizeReview ? '✓ Needs review first' : 'Sort: needs review first'}
                        </Button>
                    </div>
                    <Button
                        variant="primary"
                        onClick={() => loadRuns()}
                        disabled={isLoading}
                    >
                        {isLoading ? 'Loading...' : 'Refresh'}
                    </Button>
                </div>

                {error && <div className="text-[var(--accent-negative)] italic mb-4">{error}</div>}

                {!isLoading && !error && sortedRuns.length === 0 && (
                    <div className="text-[var(--text-muted)] italic">No chat runs recorded yet.</div>
                )}

                <div className="flex flex-col gap-2">
                    {sortedRuns.map(run => <ChatRunRow key={run.chat_id} run={run} sessionId={sessionId} />)}
                </div>
            </div>
        </div>
    )
}

export default ChatReviewPage
