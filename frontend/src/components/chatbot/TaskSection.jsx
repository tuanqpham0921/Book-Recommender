import { useState, useEffect } from 'react';
import { ChevronRight, Check, X } from 'lucide-react';

function formatArg(value) {
    if (Array.isArray(value)) return value.join(', ');
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
}

function DetailRow({ label, className = '', children }) {
    return (
        <div className="task-details-row">
            <dt>{label}</dt>
            <dd className={className}>{children}</dd>
        </div>
    );
}

/**
 * How the step was done, above its preview: the arguments the node parsed out
 * of its instruction (which is the section's title), the SQL it counted with,
 * and what it cost. Arrives on task.end with empty keys already dropped, so
 * every row is optional.
 */
function TaskDetails({ details }) {
    const {
        args, sql, error_message,
        duration, total_tokens, input_tokens, output_tokens,
    } = details;

    const cost = [
        duration != null && `${duration.toFixed(2)}s`,
        total_tokens > 0 &&
            `${total_tokens.toLocaleString()} tokens (${input_tokens} in, ${output_tokens} out)`,
    ].filter(Boolean).join(' · ');

    return (
        <dl className="task-details">
            {args && (
                <DetailRow label="Arguments">
                    {Object.entries(args).map(([key, value]) => (
                        <div key={key}>
                            <span className="task-details-key">{key}:</span> {formatArg(value)}
                        </div>
                    ))}
                </DetailRow>
            )}
            {sql && <DetailRow label="SQL"><pre>{sql}</pre></DetailRow>}
            {error_message && (
                <DetailRow label="Error" className="task-details-error">{error_message}</DetailRow>
            )}
            {cost && <DetailRow label="Cost">{cost}</DetailRow>}
        </dl>
    );
}

/**
 * One executed node, rendered as a collapsible step in the task list.
 *
 * The header is the planner's instruction for the step, beside the count the
 * node reported — the point of counts-first
 * retrieval is that "1,240 matched" is known before any rows are fetched, so
 * the number is the headline and the book cards inside are a sample of it.
 * The body is its details, then what the node streamed (its line and cards)
 * under a Preview label that says how much of the match the cards are.
 *
 * Open/closed follows the stream by default (expanded while running, folded on
 * completion) until the user clicks, after which their choice sticks.
 */
function TaskSection({ section, children }) {
    const [userToggled, setUserToggled] = useState(false);
    const [open, setOpen] = useState(section.open !== false);

    useEffect(() => {
        if (!userToggled) setOpen(section.open !== false);
    }, [section.open, userToggled]);

    const collapsible = section.collapsible !== false;
    const isOpen = collapsible ? open : true;

    // cards the node streamed — the count arrives on task.end, so until then
    // the label can only say it is a preview
    const shown = (section.sections || [])
        .filter(child => child.type === 'books')
        .reduce((total, child) => total + child.books.length, 0);
    const previewLabel = section.count != null
        ? `Preview · ${shown} of ${section.count.toLocaleString()} books`
        : 'Preview';

    const toggle = () => {
        if (!collapsible) return;
        setUserToggled(true);
        setOpen(current => !current);
    };

    return (
        <div className="task-section">
            <button
                type="button"
                onClick={toggle}
                aria-expanded={isOpen}
                className={`task-section-header ${collapsible ? '' : 'task-section-header-static'}`}
            >
                {collapsible && (
                    <ChevronRight
                        size={16}
                        className={`task-section-chevron ${isOpen ? 'task-section-chevron-open' : ''}`}
                    />
                )}
                <span className="task-section-title">{section.title}</span>

                {section.count !== null && section.count !== undefined && (
                    <span className="task-section-count">
                        {section.count.toLocaleString()}
                        {section.count === 1 ? ' book' : ' books'}
                    </span>
                )}

                {section.closed && (
                    section.ok
                        ? <Check size={14} className="task-section-status ok" />
                        : <X size={14} className="task-section-status failed" />
                )}
            </button>

            {isOpen && (
                <div className="task-section-body">
                    {/* a cancelled step closes with nothing to show */}
                    {section.details && Object.keys(section.details).length > 0 && (
                        <TaskDetails details={section.details} />
                    )}
                    {shown > 0 && <div className="ml-2 mt-5 task-preview-label">{previewLabel}</div>}
                    {children}
                </div>
            )}
        </div>
    );
}

export default TaskSection;
