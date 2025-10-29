import conversationService from '../api/services/conversationService';
import userService from '../api/services/userService';
import { Doc, GetDocsResponse } from '../models/misc';
import { GetConversationsResult, ConversationSummary } from './types';

//Fetches all JSON objects from the source. We only use the objects with the "model" property in SelectDocsModal.tsx. Hopefully can clean up the source file later.
export async function getDocs(token: string | null): Promise<Doc[] | null> {
  try {
    const response = await userService.getDocs(token);
    const data = await response.json();

    const docs: Doc[] = [];
    data.forEach((doc: object) => {
      docs.push(doc as Doc);
    });

    return docs;
  } catch (error) {
    console.log(error);
    return null;
  }
}

export async function getDocsWithPagination(
  sort = 'date',
  order = 'desc',
  pageNumber = 1,
  rowsPerPage = 10,
  searchTerm = '',
  token: string | null,
): Promise<GetDocsResponse | null> {
  try {
    const query = `sort=${sort}&order=${order}&page=${pageNumber}&rows=${rowsPerPage}&search=${searchTerm}`;
    const response = await userService.getDocsWithPagination(query, token);
    const data = await response.json();
    const docs: Doc[] = [];
    Array.isArray(data.paginated) &&
      data.paginated.forEach((doc: Doc) => {
        docs.push(doc as Doc);
      });
    return {
      docs: docs,
      totalDocuments: data.total,
      totalPages: data.totalPages,
      nextCursor: data.nextCursor,
    };
  } catch (error) {
    console.log(error);
    return null;
  }
}

export async function getConversations(
  token: string | null,
): Promise<GetConversationsResult> {
  try {
    const response = await conversationService.getConversations(token);

    if (!response.ok) {
      console.error('Error fetching conversations:', response.statusText);
      return { data: null, loading: false };
    }

    const rawData: unknown = await response.json();
    if (!Array.isArray(rawData)) {
      console.error(
        'Invalid data format received from API: Expected an array.',
        rawData,
      );
      return { data: null, loading: false };
    }

    const conversations: ConversationSummary[] = rawData.map((item: any) => ({
      id: item.id,
      name: item.name,
      agent_id: item.agent_id ?? null,
    }));
    return { data: conversations, loading: false };
  } catch (error) {
    console.error(
      'An unexpected error occurred while fetching conversations:',
      error,
    );
    return { data: null, loading: false };
  }
}

export function getLocalApiKey(): string | null {
  const key = localStorage.getItem('DocsGPTApiKey');
  return key;
}

export function getLocalRecentDocs(sourceDocs?: Doc[] | null): Doc[] | null {
  const docsString = localStorage.getItem('DocsGPTRecentDocs');
  const selectedDocs = docsString ? (JSON.parse(docsString) as Doc[]) : null;

  if (!sourceDocs || !selectedDocs || selectedDocs.length === 0) {
    return selectedDocs;
  }
  const isDocAvailable = (selected: Doc) => {
    return sourceDocs.some((source) => {
      if (source.id && selected.id) {
        return source.id === selected.id;
      }
      return source.name === selected.name && source.date === selected.date;
    });
  };

  const validDocs = selectedDocs.filter(isDocAvailable);

  setLocalRecentDocs(validDocs.length > 0 ? validDocs : null);

  return validDocs.length > 0 ? validDocs : null;
}

export function getLocalPrompt(): string | null {
  const prompt = localStorage.getItem('DocsGPTPrompt');
  return prompt;
}

export function setLocalApiKey(key: string): void {
  localStorage.setItem('DocsGPTApiKey', key);
}

export function setLocalPrompt(prompt: string): void {
  localStorage.setItem('DocsGPTPrompt', prompt);
}

export function setLocalRecentDocs(docs: Doc[] | null): void {
  if (docs && docs.length > 0) {
    localStorage.setItem('DocsGPTRecentDocs', JSON.stringify(docs));
  } else {
    localStorage.removeItem('DocsGPTRecentDocs');
  }
}
