import { useState, useEffect, useRef } from 'react'
import { useImmer } from 'use-immer';
import ChatInput from '@/components/chatbot/ChatInput'
import ChatMessages from '@/components/chatbot/ChatMessages'
import api from '@/api';
import { parseSSEStream } from '@/utils';

const DEFAULT_TIMEOUT_MS = 120000; // 2 minutes

/**
 * Where the next streamed section belongs.
 *
 * Sections are flat except for one case: while a task is open (a task.start
 * with no matching task.end), text and book cards nest inside that task so the
 * accordion can fold them away. Everything else lands at the top level, which
 * is why the plan diagram — sent before any task opens — stays outside.
 */
function openContainer(response) {
    const last = response.sections.at(-1);
    return last && last.type === 'task' && !last.closed
        ? last.sections
        : response.sections;
}

function ChatBot() {
    const messagesEndRef = useRef(null)
    const activeAbortControllerRef = useRef(null)

    const [turn, setTurn] = useImmer([])

    const [sessionId, setSessionId] = useState(null);
    const [newMessage, setNewMessage] = useState('');

    const isStreaming = turn.length && turn[turn.length - 1].response.isStreaming;

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }

    useEffect(() => {
        scrollToBottom()
    }, [turn, !isStreaming])

    async function handleSendMessage() {
        const trimmedMessage = newMessage.trim();
        if (!trimmedMessage || isStreaming) return;

        const turnID = Date.now()
        const userMessage = {
            id: turnID + '--user',
            turnId: turnID,
            text: trimmedMessage,
            isUser: true,
        }

        const botMessage = {
            id: turnID + '--bot',
            turnId: turnID,
            isUser: false,
            isLoading: true,
            loadingText: 'Sending Request...',
            isStreaming: true,
            sections: [
                // Each section is a distinct unit of response.
                // They are ordered and can be streamed incrementally.
                // Examples:
                // { id: ..., type: 'text', content: 'Analyzing Dune...' }
                // { id: ..., type: 'books', books: [...] }
                // { id: ..., type: 'diagram', mermaid: 'graph TD; ...' }
                // { id: ..., type: 'task', title: 'Found books by title',
                //   count: 4, open: true, closed: false, sections: [...] }
                //   ^ the one nesting section: text/books streamed between a
                //     task.start and its task.end land in its own list
            ],
        };

        const curTurn = { id: turnID, user: userMessage, response: botMessage }
        setTurn(draft => { draft.push(curTurn) })
        setNewMessage('')

        let sessionIdOrNew = sessionId;
        let stream = null;
        const abortController = new AbortController();
        activeAbortControllerRef.current = abortController;
        let safetyTimer = null;

        try {
            // Safety timer 
            safetyTimer = setTimeout(() => {
                console.warn('Safety timer triggered - aborting request');
                abortController.abort('Request timeout after 2 minutes');
            }, DEFAULT_TIMEOUT_MS); 

            // Sessions are created lazily on the first message — page loads
            // that never chat (bounces, review-only visits) don't write a
            // session row. Feedback filed before any message goes out with
            // session_id null, which the backend accepts.
            if (!sessionId) {
                const { id } = await api.createSession();
                setSessionId(id);
                sessionIdOrNew = id;
            }

            // Pass abort signal to API call
            stream = await api.sendChatMessage(sessionIdOrNew, trimmedMessage, abortController.signal);

            for await (const event of parseSSEStream(stream)) {
                // Check if request was aborted
                if (abortController.signal.aborted) {
                    console.log('Stream aborted by controller');
                    break;
                }

                console.log("🔗 event: ", event.type);

                // 🆔 Chat id is known before any work starts on the backend —
                // grab it immediately so feedback can attach to this run even
                // if the turn later errors, times out, or is stopped early
                if (event.type === 'chat.id') {
                    setTurn(draft => {
                        const last = draft[draft.length - 1];
                        last.response.chatId = event.data?.chat_id || null;
                    });
                    continue;
                }

                // ✅ Backend finished — carries the chat_id of the recorded
                // chat_runs row so feedback buttons can target it
                if (event.type === 'complete') {
                    setTurn(draft => {
                        const last = draft[draft.length - 1];
                        last.response.chatId = event.data?.chat_id || null;
                        last.response.isLoading = false;
                        last.response.loadingText = null;
                        last.response.isStreaming = false;
                    });
                    break;
                }

                if (event.type === 'step.complete') {
                    setTurn(draft => {
                        const last = draft[draft.length - 1];
                        last.response.isLoading = false;
                        last.response.loadingText = null;
                        last.response.isStreaming = false;
                    });
                    break;
                }

                // 🔴 ERROR HANDLING
                if (event.type === 'error') {
                    console.error('Error in handleSendMessage:', event.data);
                    setTurn(draft => {
                        const last = draft[draft.length - 1];
                        last.response.isLoading = false;
                        last.response.error = true;
                        last.response.errorText = event.data;
                        last.response.loadingText = null;
                        last.response.isStreaming = false;

                        const sectionId = `${last.response.id}-section-${last.response.sections.length + 1}`;
                        last.response.sections.push({
                            id: sectionId,
                            type: 'error',
                            content: event.data
                        });
                    });
                    break;
                }

                /// 🔄 Loading message
                if (event.type === 'ui.loading') {
                    setTurn(draft => {
                        draft[draft.length - 1].response.loadingText = event.data || 'Thinking...';
                        draft[draft.length - 1].response.isLoading = true;
                        draft[draft.length - 1].response.isStreaming = true;
                    });
                }

                /// 🟢 TEXT (streaming text deltas)
                if (event.type === 'content.delta') {
                    setTurn(draft => {
                        const last = draft[draft.length - 1];
                        last.response.isLoading = false;
                        last.response.loadingText = null;
                        last.response.isStreaming = true;

                        // Find or create the current text section
                        const container = openContainer(last.response);
                        const lastSection = container.at(-1);
                        if (!lastSection || lastSection.type !== 'text') {
                            const sectionId = `${last.response.id}-section-${container.length + 1}`;
                            container.push({
                                id: sectionId,
                                type: 'text',
                                content: ''
                            });
                        }
                        container.at(-1).content += event.data || '';
                    });
                    continue;
                }

                // 📘 BOOK CARD EVENTS
                if (event.type === 'book_card') {
                    setTurn(draft => {
                        const last = draft[draft.length - 1];
                        last.response.isStreaming = true;

                        // Check if a books section already exists
                        const container = openContainer(last.response);
                        const lastSection = container.at(-1);
                        if (!lastSection || lastSection.type !== 'books') {
                            const sectionId = `${last.response.id}-section-${container.length + 1}`;
                            container.push({
                                id: sectionId,
                                type: 'books',
                                books: []
                            });
                        }

                        // Append book data
                        container.at(-1).books.push(event.data);
                    });
                    continue;
                }

                // 🗂️ TASK SECTIONS — one per executed node. Opens expanded so
                // the user watches the step happen, then folds itself away on
                // task.end, leaving the final answer as what's still visible.
                if (event.type === 'task.start') {
                    setTurn(draft => {
                        const last = draft[draft.length - 1];
                        last.response.isStreaming = true;
                        last.response.sections.push({
                            id: `${last.response.id}-task-${event.data.task_id}`,
                            type: 'task',
                            taskId: event.data.task_id,
                            title: event.data.title,
                            collapsible: event.data.collapsible !== false,
                            count: null,
                            open: true,
                            closed: false,
                            ok: true,
                            sections: []
                        });
                    });
                    continue;
                }

                if (event.type === 'task.end') {
                    setTurn(draft => {
                        const last = draft[draft.length - 1];
                        const task = last.response.sections.at(-1);
                        // a stray end with no open task leaves nothing to close
                        if (task && task.type === 'task') {
                            task.closed = true;
                            task.count = event.data.count ?? null;
                            task.ok = event.data.ok !== false;
                            // stay open when there's nothing to fold away, or
                            // when this node owns the answer
                            task.open = !task.collapsible || task.sections.length === 0;
                        }
                    });
                    continue;
                }

                // 🧭 MERMAID DIAGRAM EVENTS
                if (event.type === 'mermaid.diagram') {
                    setTurn(draft => {
                        const last = draft[draft.length - 1];
                        last.response.isStreaming = true;
                        const sectionId = `${last.response.id}-section-${last.response.sections.length + 1}`;
                        last.response.sections.push({
                            id: sectionId,
                            type: 'diagram',
                            mermaid: event.data
                        });
                    });
                    continue;
                }

                console.log("----------------------------")
                console.log(turn)
                console.log("----------------------------")

            }

        } catch (err) {
            console.error(err);

            // Handle abort error specifically
            if (err.name === 'AbortError' || abortController.signal.aborted) {
                const userStopped = abortController.signal.reason === 'user_stop';
                setTurn(draft => {
                    if (!draft.length) return;
                    const last = draft[draft.length - 1];
                    last.response.isLoading = false;
                    last.response.loadingText = null;
                    last.response.isStreaming = false;

                    // User-initiated stop isn't an error — leave whatever
                    // was already streamed as the final response, ChatGPT-style
                    if (userStopped) return;

                    const sectionId = `${last.response.id}-section-${last.response.sections.length + 1}`;
                    last.response.sections.push({
                        id: sectionId,
                        type: 'error',
                        content: "Request timed out after 3 minutes"
                    });
                });
            } else {
                // Handle other errors
                setTurn(draft => {
                    if (!draft.length) return;
                    const last = draft[draft.length - 1];
                    last.response.isLoading = false;
                    last.response.loadingText = null;
                    last.response.isStreaming = false;

                    const sectionId = `${last.response.id}-section-${last.response.sections.length + 1}`;
                    last.response.sections.push({
                        id: sectionId,
                        type: 'error',
                        content: "Oops something went wrong..."
                    });
                });
            }
        } finally {
            // Clear safety timer
            if (safetyTimer) {
                clearTimeout(safetyTimer);
                safetyTimer = null;
            }

            // Abort any ongoing request if still active
            if (abortController && !abortController.signal.aborted) {
                abortController.abort('Cleanup');
            }
            if (activeAbortControllerRef.current === abortController) {
                activeAbortControllerRef.current = null;
            }

            // Safety net to ensure that we set streaming is done
            setTurn(draft => {
                if (!draft.length) return;
                const last = draft[draft.length - 1];
                last.response.isLoading = false;
                last.response.loadingText = null;
                last.response.isStreaming = false;
            });
        }
    }

    function handleStop() {
        activeAbortControllerRef.current?.abort('user_stop');
    }

    return (
        <div className="flex flex-col h-full w-full min-w-0 min-h-0">
                <div className="flex-1 min-h-0 min-w-0 overflow-hidden pl-3 mr-3">
                    {turn.length === 0 ? (
                        <div className="h-full w-full flex items-center justify-center text-[var(--text-hover)] italic text-2xl">
                            What are you in the mood to read today?
                        </div>
                    ) : (
                        <ChatMessages messages={turn} />
                    )}
                </div>
                <div className="flex-shrink-0 min-w-0">
                    <ChatInput
                        newMessage={newMessage}
                        isStreaming={isStreaming}
                        setNewMessage={setNewMessage}
                        onSendMessage={handleSendMessage}
                        onStop={handleStop}
                    />
                </div>
        </div>
    )
}

export default ChatBot
