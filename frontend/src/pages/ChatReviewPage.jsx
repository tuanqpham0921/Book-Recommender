import { useState, useEffect } from 'react'
import { MessageCircle, ThumbsUp, ThumbsDown } from 'lucide-react'
import api from '@/api'
import { IssueReportModal } from '@/components/chatbot/ChatFeedback'
import Button from '@/design-system/Button'
import IconButton from '@/design-system/IconButton'
import Badge from '@/design-system/Badge'
import Emoji from '@/design-system/Emoji'

// The end user's own reaction recorded on the run (chat_runs.liked).
function FeedbackBadge({ run }) {
    if (run.liked === false) return <Badge tone="negative" title="Disliked"><Emoji>👎</Emoji> disliked</Badge>
    if (run.liked === true) return <Badge tone="positive" title="Liked"><Emoji>👍</Emoji> liked</Badge>
    return <Badge tone="neutral">— unreviewed</Badge>
}

function StatusBadge({ ok }) {
    if (ok === true) return <Badge tone="positive">ok</Badge>
    if (ok === false) return <Badge tone="negative">failed</Badge>
    return <Badge tone="neutral">unknown</Badge>
}

// One chat run row: summary line + expandable detail (metadata, reviewer
// reaction, written reports).
function ChatRunRow({ run, sessionId }) {
    const [expanded, setExpanded] = useState(false)
    const [feedback, setFeedback] = useState(null)
    const [showFeedbackModal, setShowFeedbackModal] = useState(false)
    const [isSavingReaction, setIsSavingReaction] = useState(false)

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
                    <Badge tone="negative" className="mt-0.5 border border-[var(--accent-negative-border)] whitespace-nowrap">
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
                        <div className="flex flex-col gap-2">
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
                    )}
                </div>
            )}
        </div>
    )
}

// Internal review page: lists every recorded chat run, newest first, with a
// simple search by session id.
function ChatReviewPage() {
    const [runs, setRuns] = useState([])
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState(null)
    const [sessionSearch, setSessionSearch] = useState('')
    // Own session, separate from any live chat session — feedback filed
    // from this page is tagged review=true and shouldn't be grouped under
    // whatever session a visitor's actual chat conversation is using.
    const [sessionId, setSessionId] = useState(null)

    async function loadRuns(search = sessionSearch) {
        setIsLoading(true)
        setError(null)
        try {
            const data = await api.getChatRuns(200, 0, search.trim() || null)
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

    useEffect(() => {
        loadRuns('')
    }, [])

    return (
        <div className="min-h-full bg-[var(--bg-secondary)]">
            <div className="max-w-4xl mx-auto px-4 py-4">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                        <span className="text-sm text-[var(--text-inactive)]">
                            {isLoading ? 'Loading runs…' : `${runs.length} chat run${runs.length === 1 ? '' : 's'}`}
                        </span>
                        <input
                            value={sessionSearch}
                            onChange={e => setSessionSearch(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') loadRuns() }}
                            placeholder="Search by session id"
                            className="px-2 py-1 text-sm border border-[var(--border-light)] rounded bg-[var(--bg-primary)] text-[var(--text-active)]"
                        />
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

                {!isLoading && !error && runs.length === 0 && (
                    <div className="text-[var(--text-muted)] italic">No chat runs recorded yet.</div>
                )}

                <div className="flex flex-col gap-2">
                    {runs.map(run => <ChatRunRow key={run.chat_id} run={run} sessionId={sessionId} />)}
                </div>
            </div>
        </div>
    )
}

export default ChatReviewPage
