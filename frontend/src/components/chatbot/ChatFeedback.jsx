import { useState } from 'react'
import api from '@/api'

// Like / dislike / comment controls shown at the end of a finished bot
// response. Updates the chat_runs row identified by chatId.
function ChatFeedback({ chatId }) {
    const [liked, setLiked] = useState(null)          // null | true | false
    const [showComment, setShowComment] = useState(false)
    const [comment, setComment] = useState('')
    const [commentSaved, setCommentSaved] = useState(false)
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

    async function handleCommentSubmit() {
        const trimmed = comment.trim()
        if (!trimmed || isSaving) return
        setError(null)
        setIsSaving(true)
        try {
            await api.updateChatFeedback(chatId, { comment: trimmed })
            setCommentSaved(true)
            setShowComment(false)
        } catch (err) {
            console.error('Failed to save comment:', err)
            setError('Could not save comment')
        } finally {
            setIsSaving(false)
        }
    }

    return (
        <div className="mt-2 ml-1">
            <div className="flex items-center gap-2">
                <button
                    type="button"
                    onClick={() => handleReaction(true)}
                    disabled={isSaving}
                    title="Good response"
                    className={`px-2 py-1 rounded-md text-sm transition-colors ${
                        liked === true
                            ? 'bg-green-100 text-green-700'
                            : 'text-gray-400 hover:text-green-600 hover:bg-gray-100'
                    }`}
                >
                    👍
                </button>
                <button
                    type="button"
                    onClick={() => handleReaction(false)}
                    disabled={isSaving}
                    title="Bad response"
                    className={`px-2 py-1 rounded-md text-sm transition-colors ${
                        liked === false
                            ? 'bg-red-100 text-red-700'
                            : 'text-gray-400 hover:text-red-600 hover:bg-gray-100'
                    }`}
                >
                    👎
                </button>
                <button
                    type="button"
                    onClick={() => setShowComment(prev => !prev)}
                    disabled={isSaving}
                    title="Leave a comment"
                    className="px-2 py-1 rounded-md text-sm text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
                >
                    💬
                </button>
                {commentSaved && !showComment && (
                    <span className="text-xs text-gray-400 italic">Comment saved</span>
                )}
                {error && (
                    <span className="text-xs text-red-500 italic">{error}</span>
                )}
            </div>

            {showComment && (
                <div className="mt-2 flex items-start gap-2">
                    <textarea
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                        placeholder="What was good or bad about this response?"
                        rows={2}
                        className="flex-1 max-w-md text-sm border border-gray-300 rounded-md p-2 focus:outline-none focus:ring-1 focus:ring-gray-400 resize-none"
                    />
                    <button
                        type="button"
                        onClick={handleCommentSubmit}
                        disabled={isSaving || !comment.trim()}
                        className="px-3 py-1.5 text-sm rounded-md bg-gray-800 text-white disabled:opacity-40 hover:bg-gray-700 transition-colors"
                    >
                        {isSaving ? 'Saving...' : 'Save'}
                    </button>
                </div>
            )}
        </div>
    )
}

export default ChatFeedback
