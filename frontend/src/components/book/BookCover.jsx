const FALLBACK_COVER = '/cover-not-found.jpg';

// Letterboxed cover — always shows the whole image (object-contain) inside
// a fixed 2:3 box instead of cropping to fill, so no title/art gets cut off
// regardless of the source image's actual aspect ratio. Grayscale until color
// mode is on (--mono-filter in styles/tokens.css), like the rest of the UI.
function BookCover({ book, className = '' }) {
  return (
    <div className={`relative aspect-[2/3] w-full overflow-hidden rounded-lg bg-[var(--bg-quaternary)] ${className}`}>
      <img
        src={book.thumbnail || FALLBACK_COVER}
        alt={book.title}
        className="absolute inset-0 h-full w-full object-contain"
        style={{ filter: 'var(--mono-filter)' }}
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
