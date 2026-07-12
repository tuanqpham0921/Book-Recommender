import { useState } from 'react';
import { formatAuthors, formatAuthorsMobile } from '@/utils/bookUtils';
import BookCover from './BookCover';
import BookDetailModal from './BookDetailModal';

// Compact tile for the horizontal chat stack — whole card is the tap
// target, opens BookDetailModal for anything that doesn't fit here.
export const BookCard = ({ book }) => {
  const [showDetail, setShowDetail] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setShowDetail(true)}
        className="bg-[var(--bg-primary)] rounded-2xl shadow-sm flex flex-col h-full p-3 text-left w-full"
      >
        <BookCover book={book} className="mb-2" />

        <h3 className="font-bold text-sm sm:text-base text-[var(--text-active)] mb-1 line-clamp-2">
          {book.title}
        </h3>

        <div className="mt-auto">
          <p className="text-[var(--text-hover)] text-xs sm:text-sm line-clamp-2">
            <span className="hidden sm:inline">{formatAuthors(book, 2)}</span>
            <span className="sm:hidden">{formatAuthorsMobile(book)}</span>
          </p>
          <p className="text-[var(--text-muted)] text-xs line-clamp-1">
            {book.categories} • {book.published_year}
          </p>
        </div>
      </button>

      <BookDetailModal book={book} isOpen={showDetail} onClose={() => setShowDetail(false)} />
    </>
  );
};

// Row layout for a full list/grid page — cover + key facts side by side,
// with a truncated description underneath. "Read more" opens the same
// BookDetailModal instead of growing the card, so cards in the scrolling
// list keep a predictable height.
export const BookCardDetailed = ({ book }) => {
  const [showDetail, setShowDetail] = useState(false);

  return (
    <>
      <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-lg p-3 mb-2 flex-shrink-0">
        <div className="flex gap-3">
          <div className="w-20 sm:w-24 flex-shrink-0">
            <BookCover book={book} />
          </div>

          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-base text-[var(--text-active)] mb-1 line-clamp-2">
              {book.title}
              <span className="text-[var(--text-muted)] text-xs sm:text-sm ml-1"> - {book.published_year}</span>
            </h3>

            <p className="text-[var(--text-hover)] text-sm line-clamp-1">
              {formatAuthors(book, 3)}
            </p>
            <p className="text-[var(--text-muted)] text-xs mt-0.5 line-clamp-1">
              {book.categories}
              {book.num_pages && ` • ${book.num_pages} pages`}
            </p>

            {book.average_rating && (
              <div className="flex items-center gap-1 mt-1 text-[var(--text-muted)] text-xs">
                <span>
                  {'★'.repeat(Math.floor(book.average_rating))}
                  {'☆'.repeat(5 - Math.floor(book.average_rating))}
                </span>
                <span>{book.average_rating}</span>
              </div>
            )}
          </div>
        </div>

        {book.description && (
          <div className="border-t border-[var(--border-light)] mt-3 pt-2">
            <p className="text-sm text-[var(--text-hover)] line-clamp-2">
              {book.description}
            </p>
            <button
              type="button"
              onClick={() => setShowDetail(true)}
              className="text-[var(--text-inactive)] hover:text-[var(--text-active)] font-medium mt-1 text-sm"
            >
              Read more
            </button>
          </div>
        )}
      </div>

      <BookDetailModal book={book} isOpen={showDetail} onClose={() => setShowDetail(false)} />
    </>
  );
};
