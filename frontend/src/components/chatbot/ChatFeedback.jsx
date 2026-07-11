import { useState } from 'react'
import api from '@/api'
import { ThumbsUp, ThumbsDown, MessageCircle, X, Flag, Sparkles, ChevronDown } from 'lucide-react';
import Button from '@/design-system/Button'
import IconButton from '@/design-system/IconButton'
import Badge from '@/design-system/Badge'
import Dropdown from '@/design-system/Dropdown'
import DropdownItem from '@/design-system/DropdownItem'

const ISSUE_CATEGORIES = [
    'Content', 'Recommendation', 'Planner', 'Time', 'UI/UX',   'Other'
]

const MAX_ISSUES_PER_MODAL = 20

// Centered popup for filing a categorized issue report against a chat run,
// or (when chatId is omitted) general feedback for the whole session.
// Appends to (and displays) the run's issue log rather than overwriting a
// single comment field.
export function IssueReportModal({ chatId, sessionId, isOpen, onClose, review = false }) {
    const [category, setCategory] = useState('')
    const [positive, setPositive] = useState(false)
    const [message, setMessage] = useState('')
    const [issues, setIssues] = useState([])
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [error, setError] = useState(null)

    async function handleSubmit() {
        const trimmed = message.trim()
        if (!trimmed || isSubmitting || issues.length >= MAX_ISSUES_PER_MODAL) return
        setError(null)
        setIsSubmitting(true)
        try {
            await api.addFeedback({ chatId, sessionId, title: category || null, message: trimmed, positive, review })
            setIssues(prev => [...prev, { title: category || null, message: trimmed, positive, created_at: new Date().toISOString() }])
            setMessage('')
        } catch (err) {
            console.error('Failed to submit report:', err)
            setError('Could not save report')
        } finally {
            setIsSubmitting(false)
        }
    }

    if (!isOpen) return null

    return (
        <div
            className="fixed inset-0 bg-black/40 backdrop-blur-xs z-50 flex items-center justify-center px-4"
            onClick={onClose}
        >
            <div
                className="bg-[var(--bg-primary)] rounded-xl shadow-xl w-full max-w-md max-h-[85vh] flex flex-col"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-light)]">
                    <h2 className="font-semibold text-[var(--text-active)]">{chatId ? 'Report on this response' : 'Overall feedback'}</h2>
                    <IconButton onClick={onClose}>
                        <X size={18} />
                    </IconButton>
                </div>

                <div className="px-5 py-4 overflow-y-auto flex-1">
                    <div className="flex gap-2 mb-3">
                        <Button
                            variant="ghost"
                            onClick={() => setPositive(false)}
                            className={`flex-1 ${!positive ? 'bg-[var(--accent-negative-bg)] border-[var(--accent-negative-border)] text-[var(--accent-negative)]' : 'border border-[var(--border-light)]'}`}
                        >
                            <Flag size={14} /> Issue
                        </Button>
                        <Button
                            variant="ghost"
                            onClick={() => setPositive(true)}
                            className={`flex-1 ${positive ? 'bg-[var(--accent-positive-bg)] border-[var(--accent-positive-border)] text-[var(--accent-positive)]' : 'border border-[var(--border-light)]'}`}
                        >
                            <Sparkles size={14} /> Praise
                        </Button>
                    </div>

                    <Dropdown
                        className="w-full mb-3"
                        panelClassName="w-full max-h-48 overflow-y-auto rounded-md"
                        trigger={({ toggle }) => (
                            <button
                                type="button"
                                onClick={toggle}
                                className="w-full flex items-center justify-between text-sm border border-[var(--border-light)] rounded-md p-2 bg-[var(--bg-primary)] text-left"
                            >
                                <span className={category ? 'text-[var(--text-active)]' : 'text-[var(--text-muted)]'}>
                                    {category || 'Select a category (optional)'}
                                </span>
                                <ChevronDown size={16} className="text-[var(--text-muted)]" />
                            </button>
                        )}
                    >
                        {({ close }) => ISSUE_CATEGORIES.map((c) => (
                            <DropdownItem
                                key={c}
                                selected={c === category}
                                onClick={() => { setCategory(c); close() }}
                            >
                                {c}
                            </DropdownItem>
                        ))}
                    </Dropdown>

                    <textarea
                        value={message}
                        onChange={(e) => {
                            if (e.target.value.length <= 500) {
                                setMessage(e.target.value)
                            }
                        }}
                        placeholder={chatId ? "What was good or bad about this response?" : "What was good or bad about your experience?"}
                        rows={3}
                        maxLength={500}
                        className="w-full text-sm border border-[var(--border-light)] rounded-md p-2 resize-none focus:outline-1 focus:outline-[var(--border-medium)]"
                    />
                    <div className="flex justify-end mb-2 px-2">
                        <span className={`text-xs ${message.length >= 450 ? 'text-[var(--accent-negative)]' : 'text-[var(--text-inactive)]'}`}>
                            {message.length}/500
                        </span>
                    </div>

                    <div className="flex items-center justify-between mb-4">
                        {error && <span className="text-xs text-[var(--accent-negative)] italic">{error}</span>}
                        <Button
                            variant="primary"
                            onClick={handleSubmit}
                            disabled={isSubmitting || !message.trim() || issues.length >= MAX_ISSUES_PER_MODAL}
                            className="ml-auto"
                        >
                            {isSubmitting ? 'Submitting...' : 'Submit'}
                        </Button>
                    </div>

                    <div className="border-t border-[var(--border-light)] pt-3">
                        <h3 className="text-xs font-semibold text-[var(--text-inactive)] uppercase mb-2">
                            {chatId ? 'Reports on this response' : 'Your feedback'}
                        </h3>
                        {issues.length === 0 && (
                            <div className="text-xs text-[var(--text-muted)] italic">No reports yet.</div>
                        )}
                        <div className="flex flex-col gap-2">
                            {[...issues].reverse().map((entry, i) => (
                                <div
                                    key={i}
                                    className="border border-[var(--border-light)] rounded-md p-2 bg-[var(--bg-secondary)]"
                                >
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
                                    </div>
                                    <div className="text-xs text-[var(--text-hover)] whitespace-pre-wrap break-words">{entry.message}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

// Like / dislike / issue-report controls shown at the end of a finished bot
// response. Updates the chat_runs row identified by chatId.
function ChatFeedback({ chatId, sessionId }) {
    const [liked, setLiked] = useState(null)          // null | true | false
    const [showModal, setShowModal] = useState(false)
    const [isSaving, setIsSaving] = useState(false)
    const [error, setError] = useState(null)

    async function handleReaction(value) {
        if (isSaving || liked === value) return
        setError(null)
        setIsSaving(true)
        try {
            await api.updateChatFeedback(chatId, { liked: value })
            setLiked(value)
        } catch (err) {
            console.error('Failed to save reaction:', err)
            setError('Could not save feedback')
        } finally {
            setIsSaving(false)
        }
    }

    return (
        <div className="ml-5">
            <div className="flex items-center">
                <IconButton
                    onClick={() => handleReaction(true)}
                    disabled={isSaving}
                    title="Good response"
                    tone="positive"
                    active={liked === true}
                >
                    <ThumbsUp size={16}/>
                </IconButton>
                <IconButton
                    onClick={() => handleReaction(false)}
                    disabled={isSaving}
                    title="Bad response"
                    tone="negative"
                    active={liked === false}
                >
                    <ThumbsDown size={16}/>
                </IconButton>
                <IconButton
                    onClick={() => setShowModal(true)}
                    disabled={isSaving || !chatId}
                    title="Report an issue"
                >
                    <MessageCircle size={16}/>
                </IconButton>
                {error && (
                    <span className="text-xs text-[var(--accent-negative)] italic">{error}</span>
                )}
            </div>

            <IssueReportModal chatId={chatId} sessionId={sessionId} isOpen={showModal} onClose={() => setShowModal(false)} />
        </div>
    )
}

export default ChatFeedback
