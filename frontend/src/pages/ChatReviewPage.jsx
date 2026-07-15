import { useState, useEffect, lazy, Suspense } from 'react'
import { ThumbsUp, ThumbsDown, X, Flag, Sparkles, ChevronDown } from 'lucide-react'
import api from '@/api'
import Button from '@/design-system/Button'
import IconButton from '@/design-system/IconButton'
import Badge from '@/design-system/Badge'
import Emoji from '@/design-system/Emoji'
import Dropdown from '@/design-system/Dropdown'
import DropdownItem from '@/design-system/DropdownItem'

const MermaidDiagram = lazy(() => import('@/components/MermaidDiagram'))

// Must match the backend's FeedbackCategory literal.
const REVIEW_CATEGORIES = ['Content', 'Recommendation', 'Planner', 'Time', 'UI/UX', 'Other']

function StatusBadge({ ok }) {
    if (ok === true) return <Badge tone="positive">ok</Badge>
    if (ok === false) return <Badge tone="negative">failed</Badge>
    return <Badge tone="neutral">unknown</Badge>
}

// Which query-suite entry produced this run, when it came from the suite
// runner. suite_case is the backend's lookup of that entry in the suite
// JSON — null when the file isn't available or the case id no longer exists.
// Flags cases whose suite entry defines no expectations yet (currently
// expected system goal types; expected_nodes is the legacy shape), so
// reviewing doubles as spotting regression-suite gaps.
function SuiteBadges({ run }) {
    if (!run.suite_name) return null
    const suiteCase = run.suite_case
    const hasExpectations =
        suiteCase?.expected_goal_types?.length > 0 || suiteCase?.expected_nodes?.length > 0
    return (
        <>
            <Badge tone="neutral" title={suiteCase?.note} className="whitespace-nowrap">
                {run.suite_name} #{run.suite_case_id}
            </Badge>
            {!suiteCase && (
                <Badge tone="negative" title="Suite file unavailable or case id not found" className="whitespace-nowrap">
                    case missing
                </Badge>
            )}
            {suiteCase && !hasExpectations && (
                <Badge tone="negative" title="This suite entry defines no expected system goals" className="whitespace-nowrap">
                    no expected goals
                </Badge>
            )}
            <GoalDiffBadge diff={run.goal_diff} />
        </>
    )
}

// Header summary of goal_diff (backend's multiset diff of the suite case's
// expected goal types vs the goals the run actually accepted). Null when the
// case defines no expectations — SuiteBadges already flags that separately.
function GoalDiffBadge({ diff }) {
    if (!diff) return null
    if (!diff.missing.length && !diff.extra.length) {
        return (
            <Badge tone="positive" title="Accepted goals match the suite's expected goal types" className="whitespace-nowrap">
                goals match
            </Badge>
        )
    }
    const parts = []
    if (diff.missing.length) parts.push(`missing: ${diff.missing.join(', ')}`)
    if (diff.extra.length) parts.push(`extra: ${diff.extra.join(', ')}`)
    return (
        <Badge tone="negative" title={parts.join(' — ')} className="whitespace-nowrap">
            goal mismatch
        </Badge>
    )
}

// Expanded-view details of the suite case behind a run: note, difficulty,
// and what the suite expects — shown above the actual system goals so a
// reviewer can compare expected vs produced without opening the JSON.
function SuiteCaseDetail({ run }) {
    if (!run.suite_name) return null
    const suiteCase = run.suite_case
    if (!suiteCase) {
        return (
            <div className="mb-3 p-2 bg-[var(--accent-negative-bg)] border border-[var(--accent-negative-border)] rounded text-xs">
                Suite case {run.suite_name} #{run.suite_case_id} could not be loaded —
                suite file unavailable or the case id no longer exists.
            </div>
        )
    }
    const expectedTypes = suiteCase.expected_goal_types
    return (
        <div className="mb-3 p-2 bg-[var(--bg-secondary)] border border-[var(--border-light)] rounded text-xs flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <span className="font-semibold">{suiteCase.suite_name} #{suiteCase.id}</span>
                {suiteCase.difficulty && <Badge tone="neutral">{suiteCase.difficulty}</Badge>}
            </div>
            {suiteCase.note && (
                <p className="text-[var(--text-inactive)] italic">{suiteCase.note}</p>
            )}
            <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold">Expected system goals:</span>
                {expectedTypes?.length > 0 ? (
                    expectedTypes.map((type, i) => (
                        <Badge key={`${type}-${i}`} tone="positive" className="whitespace-nowrap">{type}</Badge>
                    ))
                ) : (
                    <span className="text-[var(--text-muted)] italic">none defined in the suite yet</span>
                )}
            </div>
            {run.goal_diff && (
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold">vs accepted goals:</span>
                    {run.goal_diff.matched.map((type, i) => (
                        <Badge key={`matched-${type}-${i}`} tone="positive" title="Expected and produced" className="whitespace-nowrap">{type}</Badge>
                    ))}
                    {run.goal_diff.missing.map((type, i) => (
                        <Badge key={`missing-${type}-${i}`} tone="negative" title="Expected but the run never accepted this goal type" className="whitespace-nowrap">missing: {type}</Badge>
                    ))}
                    {run.goal_diff.extra.map((type, i) => (
                        <Badge key={`extra-${type}-${i}`} tone="warning" title="Accepted by the run but not expected by the suite" className="whitespace-nowrap">extra: {type}</Badge>
                    ))}
                    {!run.goal_diff.missing.length && !run.goal_diff.extra.length && (
                        <span className="text-[var(--text-muted)]">all expected goals produced</span>
                    )}
                </div>
            )}
            {suiteCase.expected_nodes?.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold">Expected nodes (legacy):</span>
                    {suiteCase.expected_nodes.map((node, i) => (
                        <Badge key={`${node}-${i}`} tone="neutral" className="whitespace-nowrap">{node}</Badge>
                    ))}
                </div>
            )}
        </div>
    )
}

// How many review sessions have filed a review of this run — derived by the
// backend from feedback rows, drives the queue order (0 first).
function ReviewCountBadge({ count }) {
    if (!count) return <Badge tone="neutral" title="No reviews yet">unreviewed</Badge>
    return (
        <Badge tone="positive" title={`${count} review${count === 1 ? '' : 's'} filed`}>
            ✓ {count} review{count === 1 ? '' : 's'}
        </Badge>
    )
}

// One already-filed review: overall reaction + its comments, read-only.
function ReviewCard({ review, isOwn }) {
    return (
        <div className="p-2 bg-[var(--bg-secondary)] border border-[var(--border-light)] rounded">
            <div className="flex items-center gap-2 mb-1">
                {review.liked === true && <Badge tone="positive"><Emoji>👍</Emoji> liked</Badge>}
                {review.liked === false && <Badge tone="negative"><Emoji>👎</Emoji> disliked</Badge>}
                <span className="text-[11px] text-[var(--text-muted)]">
                    {review.updated_at ? new Date(review.updated_at).toLocaleString() : ''}
                </span>
                <span className="text-[11px] text-[var(--text-muted)]">
                    {isOwn ? '(this session)' : `session ${review.session_id}`}
                </span>
            </div>
            <div className="flex flex-col gap-1">
                {(review.comments ?? []).map((comment, i) => (
                    <div key={i} className="text-xs">
                        {comment.title && (
                            <Badge tone={comment.positive ? 'positive' : 'negative'} className="mr-2">
                                {comment.title}
                            </Badge>
                        )}
                        <span className="text-[var(--text-hover)] whitespace-pre-wrap break-words">{comment.message}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}

// Editor for this review session's own review of one run: an overall
// like/dislike plus a list of {title, message, positive} comments, submitted
// whole. Re-submitting from the same session replaces the previous version
// (backend upserts on chat_id + session_id); after a page refresh the
// session changes, so a new submission files an additional review instead.
function ReviewEditor({ chatId, sessionId, ownReview, onSubmitted }) {
    const [liked, setLiked] = useState(ownReview?.liked ?? null)
    const [comments, setComments] = useState(ownReview?.comments ?? [])
    const [category, setCategory] = useState('')
    const [positive, setPositive] = useState(false)
    const [message, setMessage] = useState('')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [isDirty, setIsDirty] = useState(false)
    const [error, setError] = useState(null)

    const canSubmit = !isSubmitting && isDirty && (liked !== null || comments.length > 0)

    function toggleLiked(value) {
        setLiked(prev => (prev === value ? null : value))
        setIsDirty(true)
    }

    function addComment() {
        const trimmed = message.trim()
        if (!trimmed) return
        setComments(prev => [...prev, { title: category || null, message: trimmed, positive }])
        setMessage('')
        setCategory('')
        setPositive(false)
        setIsDirty(true)
    }

    function removeComment(index) {
        setComments(prev => prev.filter((_, i) => i !== index))
        setIsDirty(true)
    }

    async function handleSubmit() {
        if (!canSubmit || !sessionId) return
        setError(null)
        setIsSubmitting(true)
        try {
            const saved = await api.submitReview({ chatId, sessionId, liked, comments })
            setIsDirty(false)
            onSubmitted(saved, !ownReview)
        } catch (err) {
            console.error('Failed to submit review:', err)
            setError('Could not save review')
        } finally {
            setIsSubmitting(false)
        }
    }

    return (
        <div className="border border-[var(--border-light)] rounded-md p-3 mb-3">
            <div className="flex items-center gap-1 mb-2">
                <span className="text-xs text-[var(--text-inactive)] mr-1">Overall:</span>
                <IconButton
                    onClick={() => toggleLiked(true)}
                    disabled={isSubmitting}
                    title="I like this response"
                    tone="positive"
                    active={liked === true}
                >
                    <ThumbsUp size={14} />
                </IconButton>
                <IconButton
                    onClick={() => toggleLiked(false)}
                    disabled={isSubmitting}
                    title="I dislike this response"
                    tone="negative"
                    active={liked === false}
                >
                    <ThumbsDown size={14} />
                </IconButton>
            </div>

            {comments.length > 0 && (
                <div className="flex flex-col gap-1 mb-2">
                    {comments.map((comment, i) => (
                        <div key={i} className="flex items-start gap-2 p-2 bg-[var(--bg-secondary)] border border-[var(--border-light)] rounded text-xs">
                            {comment.title && (
                                <Badge tone={comment.positive ? 'positive' : 'negative'} className="whitespace-nowrap">
                                    {comment.title}
                                </Badge>
                            )}
                            <span className="flex-1 text-[var(--text-hover)] whitespace-pre-wrap break-words">{comment.message}</span>
                            <IconButton onClick={() => removeComment(i)} title="Remove comment" disabled={isSubmitting}>
                                <X size={12} />
                            </IconButton>
                        </div>
                    ))}
                </div>
            )}

            <div className="flex gap-2 mb-2">
                <Button
                    size="sm"
                    variant="secondary"
                    tone="negative"
                    active={!positive}
                    onClick={() => setPositive(false)}
                >
                    <Flag size={12} /> Issue
                </Button>
                <Button
                    size="sm"
                    variant="secondary"
                    tone="positive"
                    active={positive}
                    onClick={() => setPositive(true)}
                >
                    <Sparkles size={12} /> Praise
                </Button>
                <Dropdown
                    className="flex-1"
                    panelClassName="w-full max-h-48 overflow-y-auto rounded-md"
                    trigger={({ toggle }) => (
                        <button
                            type="button"
                            onClick={toggle}
                            style={{ fontSize: '0.75rem' }}
                            className="w-full flex items-center justify-between border border-[var(--border-light)] rounded-md px-2 py-1 bg-[var(--bg-primary)] text-left"
                        >
                            <span className={category ? 'text-[var(--text-active)]' : 'text-[var(--text-muted)]'}>
                                {category || 'Category (optional)'}
                            </span>
                            <ChevronDown size={14} className="text-[var(--text-muted)]" />
                        </button>
                    )}
                >
                    {({ close }) => REVIEW_CATEGORIES.map((c) => (
                        <DropdownItem
                            key={c}
                            selected={c === category}
                            onClick={() => { setCategory(c); close() }}
                        >
                            {c}
                        </DropdownItem>
                    ))}
                </Dropdown>
            </div>

            <textarea
                value={message}
                onChange={(e) => { if (e.target.value.length <= 500) setMessage(e.target.value) }}
                placeholder="What was good or bad about this response?"
                rows={2}
                maxLength={500}
                // Inline size needed to beat base.css's unlayered textarea font-size reset (mobile zoom guard)
                style={{ fontSize: '0.875rem' }}
                className="w-full text-sm border border-[var(--border-light)] rounded-md p-2 resize-none focus:outline-1 focus:outline-[var(--border-medium)]"
            />

            <div className="flex items-center justify-between mt-1">
                {error
                    ? <span className="text-xs text-[var(--accent-negative)] italic">{error}</span>
                    : <span className="text-xs text-[var(--text-muted)]">{message.length}/500</span>}
                <div className="flex gap-2">
                    <Button
                        size="sm"
                        variant="secondary"
                        onClick={addComment}
                        disabled={isSubmitting || !message.trim()}
                    >
                        Add comment
                    </Button>
                    <Button
                        size="sm"
                        variant="primary"
                        onClick={handleSubmit}
                        disabled={!canSubmit || !sessionId}
                        title={ownReview ? 'Replace your review from this session' : 'File your review'}
                    >
                        {isSubmitting ? 'Submitting…' : ownReview ? 'Update review' : 'Submit review'}
                    </Button>
                </div>
            </div>
        </div>
    )
}

// One chat run row: summary line + expandable detail (review editor, filed
// reviews, mermaid, full planner/tasks envelopes).
function ChatRunRow({ run, sessionId, onReviewSubmitted }) {
    const [expanded, setExpanded] = useState(false)
    const [feedback, setFeedback] = useState(null)
    const diagram = run.planner?.output?.diagram
    const parseResult = run.planner?.output?.parse_result
    const errorDetail = run.planner?.runtime_error

    // This session's own review, if it already filed one — the editor then
    // updates it in place instead of appending a new review.
    const ownReview = feedback?.find((entry) => entry.session_id === sessionId) ?? null

    // Load once on first expand.
    useEffect(() => {
        if (!expanded || feedback !== null) return
        api.getFeedback(run.chat_id)
            .then(data => setFeedback(data.feedback || []))
            .catch(err => {
                console.error('Failed to load reviews:', err)
                setFeedback([])
            })
    }, [expanded, feedback, run.chat_id])

    function handleSubmitted(savedReview, isNew) {
        setFeedback(prev => {
            const rest = (prev ?? []).filter(entry => entry.id !== savedReview.id)
            return [...rest, savedReview]
        })
        onReviewSubmitted(run.chat_id, isNew)
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
                <span className="mt-0.5 flex gap-1 whitespace-nowrap"><SuiteBadges run={run} /></span>
                <span className="mt-0.5 whitespace-nowrap"><ReviewCountBadge count={run.num_reviews} /></span>
                <span className="text-xs text-[var(--text-muted)] whitespace-nowrap mt-1">
                    {run.created_at ? new Date(run.created_at).toLocaleString() : ''}
                </span>
            </div>

            {expanded && (
                <div className="px-4 pb-4 border-t border-[var(--border-light)] text-sm">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 my-3 text-xs text-[var(--text-hover)]">
                        <div><span className="font-semibold">chat_id:</span> {run.chat_id}</div>
                        <div><span className="font-semibold">session:</span> {run.session_id}</div>
                        <div><span className="font-semibold">duration:</span> {run.duration_s?.toFixed?.(2) ?? '—'}s</div>
                        <div><span className="font-semibold">tokens:</span> {run.total_tokens ?? '—'}</div>
                    </div>

                    <SuiteCaseDetail run={run} />

                    {feedback === null ? (
                        <div className="text-xs text-[var(--text-muted)] italic mb-3">Loading reviews…</div>
                    ) : (
                        <>
                            <ReviewEditor
                                // Remount when this session's review appears/changes id so
                                // the editor picks up the saved version as its baseline.
                                key={ownReview?.id ?? 'new'}
                                chatId={run.chat_id}
                                sessionId={sessionId}
                                ownReview={ownReview}
                                onSubmitted={handleSubmitted}
                            />

                            {feedback.length > 0 && (
                                <details className="mb-3" open>
                                    <summary className="cursor-pointer text-[var(--text-hover)] font-semibold">
                                        Reviews ({feedback.length})
                                    </summary>
                                    <div className="mt-2 max-h-64 overflow-y-auto flex flex-col gap-2 pr-1">
                                        {feedback.map((entry) => (
                                            <ReviewCard key={entry.id} review={entry} isOwn={entry.session_id === sessionId} />
                                        ))}
                                    </div>
                                </details>
                            )}
                        </>
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

// Internal review page: a shared review queue over every recorded chat run.
// The backend orders runs by how many reviews they already have (derived
// from feedback rows, least first), so unreviewed conversations surface at
// the top for whoever opens the page — no assignments needed.
function ChatReviewPage() {
    const [runs, setRuns] = useState([])
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState(null)
    const [sessionSearch, setSessionSearch] = useState('')
    // Own session, separate from any live chat session — reviews filed from
    // this page are keyed by it, one review per (run, session). A fresh
    // session per page load means a re-visit files a new review rather than
    // editing the old one; a stable reviewer identity can replace this once
    // login exists.
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

    // Keep the derived count in sync locally after a submit (a first review
    // moves the run into the reviewed section) without a full reload.
    function handleReviewSubmitted(chatId, isNew) {
        if (!isNew) return
        setRuns(prev => prev.map(r =>
            r.chat_id === chatId ? { ...r, num_reviews: (r.num_reviews ?? 0) + 1 } : r
        ))
    }

    const unreviewedRuns = runs.filter(run => !run.num_reviews)
    const reviewedRuns = runs.filter(run => run.num_reviews > 0)

    return (
        <div className="min-h-full bg-[var(--bg-secondary)]">
            <div className="max-w-4xl mx-auto px-4 py-4">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                        <span className="text-sm text-[var(--text-inactive)]">
                            {isLoading ? 'Loading runs…' : `${unreviewedRuns.length} run${unreviewedRuns.length === 1 ? '' : 's'} awaiting review`}
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
                    {unreviewedRuns.map(run => (
                        <ChatRunRow key={run.chat_id} run={run} sessionId={sessionId} onReviewSubmitted={handleReviewSubmitted} />
                    ))}
                </div>

                {reviewedRuns.length > 0 && (
                    <div className="mt-8">
                        <h2 className="text-sm font-semibold text-[var(--text-inactive)] uppercase mb-2">
                            Reviewed runs ({reviewedRuns.length})
                        </h2>
                        <div className="flex flex-col gap-2">
                            {reviewedRuns.map(run => (
                                <ChatRunRow key={run.chat_id} run={run} sessionId={sessionId} onReviewSubmitted={handleReviewSubmitted} />
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export default ChatReviewPage
