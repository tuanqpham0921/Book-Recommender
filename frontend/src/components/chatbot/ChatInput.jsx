import { useState, useEffect, useRef } from 'react'
import { ArrowUp, MessageCircle, Plus, Square } from 'lucide-react';
import { userInputSuggestions } from '@/data/chatSuggestions';
import { IssueReportModal } from '@/components/chatbot/ChatFeedback';
import { useOutsideClick } from '@/hooks/useOutsideClick';
import IconButton from '@/design-system/IconButton';
import DropdownItem from '@/design-system/DropdownItem';

const TEXTAREA_MAX_HEIGHT_PX = 128 // keep in sync with max-h-32 below

function ChatInput({ newMessage, isStreaming, setNewMessage, onSendMessage, onStop, sessionId }) {
    const [showSuggestions, setShowSuggestions] = useState(true)
    const [showFeedbackModal, setShowFeedbackModal] = useState(false)
    const suggestionsRef = useRef(null) // Ref for the suggestions container
    const hintsButtonRef = useRef(null) // Ref for the hints button
    const textareaRef = useRef(null) // Ref for auto-growing the textarea

    // Grow the textarea with its content up to a max height, then let it
    // scroll internally — keeps the button row below it instead of the
    // buttons overlapping wrapped text.
    useEffect(() => {
        const el = textareaRef.current
        if (!el) return
        el.style.height = 'auto'
        el.style.height = `${Math.min(el.scrollHeight, TEXTAREA_MAX_HEIGHT_PX)}px`
    }, [newMessage])

    // Suggestions panel spans the full width of the input box, not just the
    // small hints button that opens it, so it can't be anchored the way the
    // generic Dropdown component anchors its panel — but it still shares the
    // same outside-click-to-close behavior via this hook.
    useOutsideClick([suggestionsRef, hintsButtonRef], () => setShowSuggestions(false), showSuggestions)

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !isStreaming) {
            e.preventDefault()
            onSendMessage()
        }
    }

    const handleSuggestionClick = (suggestion) => {
        setShowSuggestions(false)
        setNewMessage(suggestion.text)
    }

    return (
        <div className="bg-[var(--bg-secondary)] p-4 pt-2 pr-6">
            <div className='outline rounded-xl bg-[var(--bg-primary)] relative shadow-lg'>
                {/* Hints Dropup Menu */}
                {showSuggestions && (
                    <div
                        ref={suggestionsRef} // Attach ref to suggestions container
                        className="absolute bottom-full left-0 right-0 mb-2 bg-[var(--bg-secondary)] border border-[var(--border-light)] rounded-lg shadow-lg max-h-48 overflow-y-auto z-10"
                    >
                        <div className="sticky top-0 bg-[var(--bg-secondary)] z-20 border-b border-[var(--border-light)]">
                            <div className="text-xs text-[var(--text-inactive)] p-2 px-5">Quick suggestions:</div>
                        </div>
                        <div className="p-2 pt-0">
                            {userInputSuggestions.map((suggestion) => (
                                <DropdownItem
                                    key={suggestion.id}
                                    onClick={() => handleSuggestionClick(suggestion)}
                                    className="rounded"
                                >
                                    {suggestion.text}
                                </DropdownItem>
                            ))}
                        </div>
                    </div>
                )}

                <textarea
                    ref={textareaRef}
                    className="w-full max-h-32 text-lg px-4 py-3 bg-transparent border resize-none border-none outline-none overflow-y-auto"
                    value={newMessage}
                    onChange={e => {
                        if (e.target.value.length <= 500) {
                            setNewMessage(e.target.value)
                        }
                    }}
                    onKeyDown={handleKeyDown}
                    onFocus={() => setShowSuggestions(false)} // Hide hints when typing
                    placeholder="Hints button is available at the bottom..."
                    maxLength={500}
                    rows={1}
                    style={{ minHeight: '2.5rem' }}
                />

                {/* Button row - always its own space below the textarea, so
                    wrapped/multi-line text never sits under the icons */}
                <div className="flex items-center justify-end gap-1 px-2 pb-2">
                    {/* Overall Feedback Button */}
                    <IconButton
                        onClick={() => setShowFeedbackModal(true)}
                        title="Share overall feedback"
                    >
                        <MessageCircle size={20} />
                    </IconButton>

                    {/* Hints Button */}
                    <IconButton
                        ref={hintsButtonRef} // Attach ref to hints button
                        onClick={() => setShowSuggestions(!showSuggestions)}
                        title="Show quick suggestions"
                    >
                        <Plus size={20} />
                    </IconButton>

                    {/* Send / Stop Button */}
                    <button
                        type={isStreaming ? 'button' : 'submit'}
                        className={`p-2 rounded-full transition-all duration-200 ${
                            isStreaming || newMessage.trim()
                                ? 'bg-[var(--btn-primary-bg)] text-[var(--bg-primary)]'
                                : 'text-[var(--text-hover)] hover:bg-[var(--bg-tertiary)]'
                        }`}
                        onClick={isStreaming ? onStop : onSendMessage}
                        disabled={!isStreaming && !newMessage.trim()}
                        title={isStreaming ? 'Stop generating' : 'Send message'}
                    >
                        {isStreaming ? <Square size={16} fill="currentColor" /> : <ArrowUp size={20} />}
                    </button>
                </div>
            </div>

            {/* Character Counter */}
            <div className="flex justify-end mt-1 px-2">
                <span className={`text-xs ${newMessage.length >= 450 ? 'text-[var(--accent-negative)]' : 'text-[var(--text-inactive)]'}`}>
                    {newMessage.length}/500
                </span>
            </div>

            <IssueReportModal
                chatId={null}
                sessionId={sessionId}
                isOpen={showFeedbackModal}
                onClose={() => setShowFeedbackModal(false)}
            />
        </div>
    )
}

export default ChatInput
