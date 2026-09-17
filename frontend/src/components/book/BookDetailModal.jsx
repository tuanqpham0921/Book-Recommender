import Modal from '@/design-system/Modal';
import BookCover from './BookCover';
import { formatAuthors } from '@/utils/bookUtils';

// Full-info popup opened from either card variant — everything that doesn't
// fit (or shouldn't be forced to fit) in a compact card lives here instead:
// full-size cover, full author list, full description.
function BookDetailModal({ book, isOpen, onClose }) {
  if (!book) return null;

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={book.title}>
      <div className="flex flex-col gap-4">
        <div className="mx-auto w-32 sm:w-40">
          <BookCover book={book} />
        </div>

        <div>
          <p className="text-[var(--text-hover)] text-sm">{formatAuthors(book, 5)}</p>
          <p className="text-[var(--text-muted)] text-xs mt-1">
            {[book.categories, book.published_year, book.num_pages && `${book.num_pages} pages`]
              .filter(Boolean)
              .join(' • ')}
          </p>
          {book.average_rating && (
            <div className="flex items-center gap-1 mt-1 text-[var(--text-muted)] text-sm">
              <span>
                {'★'.repeat(Math.round(book.average_rating))}
                {'☆'.repeat(5 - Math.round(book.average_rating))}
              </span>
              <span>{book.average_rating}</span>
            </div>
          )}
        </div>

        {book.description && (
          <p className="text-[var(--text-hover)] text-sm leading-relaxed whitespace-pre-wrap">
            {book.description}
          </p>
        )}
      </div>
    </Modal>
  );
}

export default BookDetailModal;
