const FALLBACK_COVER = '/cover-not-found.jpg';

// Letterboxed cover — always shows the whole image (object-contain) inside
// a fixed 2:3 box instead of cropping to fill, so no title/art gets cut off
// regardless of the source image's actual aspect ratio.
function BookCover({ book, className = '' }) {
  return (
    <div className={`relative aspect-[2/3] w-full overflow-hidden rounded-lg bg-[var(--bg-quaternary)] ${className}`}>
      <img
        src={book.thumbnail || FALLBACK_COVER}
        alt={book.title}
        className="absolute inset-0 h-full w-full object-contain"
        onError={(e) => {
          if (e.target.src !== window.location.origin + FALLBACK_COVER) {
            e.target.src = FALLBACK_COVER;
          }
        }}
      />
    </div>
  );
}

export default BookCover;
