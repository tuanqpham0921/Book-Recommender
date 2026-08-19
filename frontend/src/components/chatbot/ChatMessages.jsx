import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useRef, useEffect, useState, lazy, Suspense } from 'react'
import { Copy, Check } from 'lucide-react';
import { BookGridStack } from '@/components/book/BooksGrid';
import TaskSection from '@/components/chatbot/TaskSection';

// Dynamic import for MermaidDiagram (large library)
const MermaidDiagram = lazy(() => import('@/components/MermaidDiagram'));

// Loading component for Mermaid
const MermaidLoading = () => (
    <div className="message-bubble response">
        <div className="flex items-center justify-center h-32">
            <div className="loading-spinner"></div>
            <span className="ml-2 text-[var(--text-hover)]">Loading diagram...</span>
        </div>
    </div>
);

/**
 * Render one section. Pulled out of the map so `task` sections can call it on
 * their own children — that nesting is the only recursion in the tree, and it
 * is one level deep: a task holds text and books, never another task.
 */
function renderSection(section, responseId, sectionIndex) {
    const key = section.id || `${responseId}-section-${sectionIndex}`;

    // Task section — a step in the plan, holding its own sections
    if (section.type === 'task') {
        return (
            <TaskSection key={key} section={section}>
                {(section.sections || []).map((child, childIndex) =>
                    renderSection(child, key, childIndex)
                )}
            </TaskSection>
        );
    }

    // Text section
    if (section.type === 'text' && section.content) {
        return (
            <div key={key} className="message-bubble response markdown-container">
                <Markdown remarkPlugins={[remarkGfm]}>{section.content}</Markdown>
            </div>
        );
    }

    // Books section
    if (section.type === 'books' && section.books && section.books.length > 0) {
        return (
            <div key={key} className="book-cards-container mb-5">
                <BookGridStack books={section.books} />
            </div>
        );
    }

    // Diagram section
    if (section.type === 'diagram' && section.mermaid) {
        return (
            <Suspense key={key} fallback={<MermaidLoading />}>
                <div className="message-bubble response">
                    <MermaidDiagram chart={section.mermaid} className="w-full" />
                </div>
            </Suspense>
        );
    }

    // Error section
    if (section.type === 'error' && section.content) {
        return (
            <div key={key} className="message-bubble text-[var(--accent-negative)] italic mt-2">
                <span>{section.content}</span>
            </div>
        );
    }

    return null;
}

function ChatMessages({ messages }) {
    const containerRef = useRef(null)
    const userMessageRefs = useRef({})
    const turnRefs = useRef({})
    const lastUserMessageId = useRef(null)
    const [copiedId, setCopiedId] = useState(null)

    const handleCopy = async (text, id) => {
        await navigator.clipboard.writeText(text)
        setCopiedId(id)
        setTimeout(() => setCopiedId(current => current === id ? null : current), 1500)
    }

    const scrollToNewestTurn = () => {
        if (messages.length > 0) {
            const newestTurn = messages[messages.length - 1]
            const turnRef = turnRefs.current[newestTurn.id]
            if (turnRef) {
                turnRef.scrollIntoView({ behavior: 'smooth', block: 'start' })
            }
        }
    }

    useEffect(() => {
        if (messages.length > 0) {
            const newestTurn = messages[messages.length - 1]
            if (newestTurn.user && newestTurn.user.id !== lastUserMessageId.current) {
                lastUserMessageId.current = newestTurn.user.id
                scrollToNewestTurn()
            }
        }
    }, [messages])

    return (
        <div ref={containerRef} className="chat-messages-container">
            {messages.map(({ id, user, response }, index) => (
                <div
                    key={id}
                    data-turn-id={id}
                    ref={(el) => turnRefs.current[id] = el}
                    className={`turn-container ${index === messages.length - 1 ? 'min-h-[95%]' : 'min-h-0'} `}
                >
                    {/* User message */}
                    <div data-user-id={user.id}
                        className="message-wrapper user relative"
                        ref={user.isUser ? (el) => userMessageRefs.current[user.id] = el : null}
                    >
                        <div className="message-bubble user">
                            {user.text}
                        </div>
                        <button
                            type="button"
                            onClick={() => handleCopy(user.text, user.id)}
                            title="Copy message"
                            className="ml-2 self-end rounded-md text-[var(--text-muted)] hover:text-[var(--text-hover)] transition-colors"
                        >
                            {copiedId === user.id ? <Check size={16} /> : <Copy size={16} />}
                        </button>
                    </div>

                    <div data-response-id={response.id} className="flex flex-col message-wrapper response">

                        {/* SECTIONS-BASED RENDERING WITH STABLE IDs */}
                        {response.sections && response.sections.length > 0 && (
                            // Render sections in order using stable section IDs
                            response.sections.map((section, sectionIndex) =>
                                renderSection(section, response.id, sectionIndex)
                            )
                        )}

                        {/* Loading state */}
                        {response.isLoading && response.isStreaming && (
                            <div className="loading-wrapper">
                                <div className="loading-spinner" />
                                <span className="loading-text">{response.loadingText}</span>
                            </div>
                        )}

                        {/* AI disclaimer - show on last message */}
                        {index === messages.length - 1 && !response.isLoading && !response.isStreaming && (
                            (response.sections?.length > 0 || response.text) && (
                                <div className="flex justify-end mt-5 mr-2">
                                    <span className="text-xs text-[var(--text-muted)] italic">
                                        AI can make mistakes. Please double-check responses.
                                    </span>
                                </div>
                            )
                        )}

                    </div>
                </div>
            ))}
        </div>
    )
}

export default ChatMessages
