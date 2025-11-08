-- Rename "Strong Female Lead" to "Badass FMC"
UPDATE public.book_reviews
SET trope_1 = 'Badass FMC'
WHERE trope_1 = 'Strong Female Lead';
UPDATE public.book_reviews
SET trope_2 = 'Badass FMC'
WHERE trope_2 = 'Strong Female Lead';
UPDATE public.book_reviews
SET trope_3 = 'Badass FMC'
WHERE trope_3 = 'Strong Female Lead';

-- Rename selected tropes to "Shadow Daddy"
UPDATE public.book_reviews
SET trope_1 = 'Shadow Daddy'
WHERE trope_1 IN (
  'Light & Dark Magic Pairing', 'The Dark Lord', 'Angel x Demon Romance',
  'morally gray protagonists', 'Enemies with Opposing Powers', 'The Cursed Hero'
);
UPDATE public.book_reviews
SET trope_2 = 'Shadow Daddy'
WHERE trope_2 IN (
  'Light & Dark Magic Pairing', 'The Dark Lord', 'Angel x Demon Romance',
  'morally gray protagonists', 'Enemies with Opposing Powers', 'The Cursed Hero'
);
UPDATE public.book_reviews
SET trope_3 = 'Shadow Daddy'
WHERE trope_3 IN (
  'Light & Dark Magic Pairing', 'The Dark Lord', 'Angel x Demon Romance',
  'morally gray protagonists', 'Enemies with Opposing Powers', 'The Cursed Hero'
);

-- Rename selected tropes to "Touch-Starved Love Interest"
UPDATE public.book_reviews
SET trope_1 = 'Touch-Starved Love Interest'
WHERE trope_1 IN ('The Misunderstood Monster', 'Romance That Affects Magic Balance', 'The Immortal Being');
UPDATE public.book_reviews
SET trope_2 = 'Touch-Starved Love Interest'
WHERE trope_2 IN ('The Misunderstood Monster', 'Romance That Affects Magic Balance', 'The Immortal Being');
UPDATE public.book_reviews
SET trope_3 = 'Touch-Starved Love Interest'
WHERE trope_3 IN ('The Misunderstood Monster', 'Romance That Affects Magic Balance', 'The Immortal Being');

-- Rename "The Antihero" and "The Betrayer" to "Burn the World for You"
UPDATE public.book_reviews
SET trope_1 = 'Burn the World for You'
WHERE trope_1 IN ('The Antihero', 'The Betrayer');
UPDATE public.book_reviews
SET trope_2 = 'Burn the World for You'
WHERE trope_2 IN ('The Antihero', 'The Betrayer');
UPDATE public.book_reviews
SET trope_3 = 'Burn the World for You'
WHERE trope_3 IN ('The Antihero', 'The Betrayer');

-- Rename "Magical Contracts with Consequences" and "Magical Bargain for Love" to "Magical Bargains"
UPDATE public.book_reviews
SET trope_1 = 'Magical Bargains'
WHERE trope_1 IN ('Magical Contracts with Consequences', 'Magical Bargain for Love');
UPDATE public.book_reviews
SET trope_2 = 'Magical Bargains'
WHERE trope_2 IN ('Magical Contracts with Consequences', 'Magical Bargain for Love');
UPDATE public.book_reviews
SET trope_3 = 'Magical Bargains'
WHERE trope_3 IN ('Magical Contracts with Consequences', 'Magical Bargain for Love');

-- Rename "Cursed to Love" to "Love Breaking a Curse"
UPDATE public.book_reviews
SET trope_1 = 'Love Breaking a Curse'
WHERE trope_1 = 'Cursed to Love';
UPDATE public.book_reviews
SET trope_2 = 'Love Breaking a Curse'
WHERE trope_2 = 'Cursed to Love';
UPDATE public.book_reviews
SET trope_3 = 'Love Breaking a Curse'
WHERE trope_3 = 'Cursed to Love';
