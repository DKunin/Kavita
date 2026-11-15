export interface WantToFind {
  id: number;
  title: string;
  authors: string;
  summary?: string;
  isbn?: string;
  externalId?: string;
  coverUrl?: string;
  sourceUrl?: string;
  notes?: string;
  createdUtc: string;
  lastModifiedUtc: string;
}

export type UpsertWantToFind = Omit<WantToFind, 'createdUtc' | 'lastModifiedUtc'>;
