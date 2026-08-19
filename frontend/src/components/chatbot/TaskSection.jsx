import { useState, useEffect } from 'react';
import { ChevronRight, Check, X } from 'lucide-react';

/**
 * One executed node, rendered as a collapsible step in the task list.
 *
 * The header carries the count the node reported — the point of counts-first
 * retrieval is that "1,240 matched" is known before any rows are fetched, so
 * the number is the headline and the book cards inside are a sample of it.
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

            {isOpen && <div className="task-section-body">{children}</div>}
        </div>
    );
}

export default TaskSection;
