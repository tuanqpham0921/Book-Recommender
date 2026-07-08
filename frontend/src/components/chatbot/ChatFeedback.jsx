import { useState, useEffect, useRef } from 'react'
import api from '@/api'
import { ThumbsUp, ThumbsDown, MessageCircle, X, Flag, Sparkles, ChevronDown } from 'lucide-react';

const ISSUE_CATEGORIES = ['Inaccurate', 'Hallucination', 'UI', 'Other']

// Centered popup for filing a categorized issue report against a chat run.
// Appends to (and displays) the run's issue log rather than overwriting a
// single comment field.
function IssueReportModal({ chatId, isOpen, onClose }) {
    const [category, setCategory] = useState('')
    const [isCategoryOpen, setIsCategoryOpen] = useState(false)
    const categoryRef = useRef(null)
    const [positive, setPositive] = useState(false)
    const [message, setMessage] = useState('')
    const [issues, setIssues] = useState([])
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [error, setError] = useState(null)

    // Close category dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event) => {
            if (categoryRef.current && !categoryRef.current.contains(event.target)) {
                setIsCategoryOpen(false)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])

    async function handleSubmit() {
        const trimmed = message.trim()
        if (!trimmed || isSubmitting) return
        setError(null)
        setIsSubmitting(true)
        try {
            await api.addChatIssue(chatId, { title: category || null, message: trimmed, positive })
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
                className="bg-white rounded-xl shadow-xl w-full max-w-md max-h-[85vh] flex flex-col"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
                    <h2 className="font-semibold text-gray-800">Report on this response</h2>
                    <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700">
                        <X size={18} />
                    </button>
                </div>

                <div className="px-5 py-4 overflow-y-auto flex-1">
                    <div className="flex gap-2 mb-3">
                        <button
                            type="button"
                            onClick={() => setPositive(false)}
                            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-sm border transition-colors ${
                                !positive
                                    ? 'bg-red-50 border-red-200 text-red-600'
                                    : 'border-gray-200 text-gray-400 hover:text-gray-600'
                            }`}
                        >
                            <Flag size={14} /> Issue
                        </button>
                        <button
                            type="button"
                            onClick={() => setPositive(true)}
                            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-sm border transition-colors ${
                                positive
                                    ? 'bg-green-50 border-green-200 text-green-600'
                                    : 'border-gray-200 text-gray-400 hover:text-gray-600'
                            }`}
                        >
                            <Sparkles size={14} /> Praise
                        </button>
                    </div>

                    <div className="relative mb-3" ref={categoryRef}>
                        <button
                            type="button"
                            onClick={() => setIsCategoryOpen(prev => !prev)}
                            className="w-full flex items-center justify-between text-sm border border-gray-200 rounded-md p-2 bg-white text-left"
                        >
                            <span className={category ? 'text-gray-800' : 'text-gray-400'}>
                                {category || 'Select a category (optional)'}
                            </span>
                            <ChevronDown size={16} className="text-gray-400" />
                        </button>

                        {isCategoryOpen && (
                            <div className="absolute top-full left-0 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg z-10">
                                {ISSUE_CATEGORIES.map((c) => (
                                    <button
                                        key={c}
                                        type="button"
                                        onClick={() => { setCategory(c); setIsCategoryOpen(false) }}
                                        className={`block w-full px-3 py-2 text-left text-sm transition-colors hover:bg-gray-100 ${
                                            c === category ? 'bg-gray-50 text-gray-900 font-medium' : 'text-gray-700'
                                        }`}
                                    >
                                        {c}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    <textarea
                        value={message}
                        onChange={(e) => {
                            if (e.target.value.length <= 500) {
                                setMessage(e.target.value)
                            }
                        }}
                        placeholder="What was good or bad about this response?"
                        rows={3}
                        maxLength={500}
                        className="w-full text-sm border border-gray-200 rounded-md p-2 resize-none focus:outline-1 focus:outline-gray-300"
                    />
                    <div className="flex justify-end mb-2 px-2">
                        <span className={`text-xs ${message.length >= 450 ? 'text-red-500' : 'text-gray-500'}`}>
                            {message.length}/500
                        </span>
                    </div>

                    <div className="flex items-center justify-between mb-4">
                        {error && <span className="text-xs text-red-500 italic">{error}</span>}
                        <button
                            type="button"
                            onClick={handleSubmit}
                            disabled={isSubmitting || !message.trim()}
                            className="ml-auto px-3 py-1.5 text-sm rounded-md bg-gray-800 text-white disabled:opacity-40 hover:bg-gray-700 transition-colors"
                        >
                            {isSubmitting ? 'Submitting...' : 'Submit'}
                        </button>
                    </div>

                    <div className="border-t border-gray-100 pt-3">
                        <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">
                            Reports on this response
                        </h3>
                        {issues.length === 0 && (
                            <div className="text-xs text-gray-400 italic">No reports yet.</div>
                        )}
                        <div className="flex flex-col gap-2">
                            {[...issues].reverse().map((entry, i) => (
                                <div
                                    key={i}
                                    className="border border-gray-100 rounded-md p-2 bg-gray-50"
                                >
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
                                    <div className="text-xs text-gray-700 whitespace-pre-wrap break-words">{entry.message}</div>
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
function ChatFeedback({ chatId }) {
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
                <button
                    type="button"
                    onClick={() => handleReaction(true)}
                    disabled={isSaving}
                    title="Good response"
                    className={`px-2 py-1 rounded-md text-sm transition-colors ${
                        liked === true
                            ? 'text-gray-700'
                            : 'text-gray-400 hover:text-gray-700'
                    }`}
                >
                    <ThumbsUp size={16}/>
                </button>
                <button
                    type="button"
                    onClick={() => handleReaction(false)}
                    disabled={isSaving}
                    title="Bad response"
                    className={`px-2 py-1 rounded-md text-sm transition-colors ${
                        liked === false
                            ? 'text-gray-700'
                            : 'text-gray-400 hover:text-gray-700'
                    }`}
                >
                    <ThumbsDown size={16}/>
                </button>
                <button
                    type="button"
                    onClick={() => setShowModal(true)}
                    disabled={isSaving || !chatId}
                    title="Report an issue"
                    className="px-2 py-1 rounded-md text-sm text-gray-400 hover:text-gray-700 transition-colors"
                >
                    <MessageCircle size={16}/>
                </button>
                {error && (
                    <span className="text-xs text-red-500 italic">{error}</span>
                )}
            </div>

            <IssueReportModal chatId={chatId} isOpen={showModal} onClose={() => setShowModal(false)} />
        </div>
    )
}

export default ChatFeedback
