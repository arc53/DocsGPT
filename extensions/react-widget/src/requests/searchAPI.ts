import { Result } from "@/types";

  async function getSearchResults(question: string, apiKey:string, apiHost:string): Promise<Result[]> {
 
    const payload = {
      question,
      api_key:apiKey
    };
  
    try {
      const response = await fetch(`${apiHost}/api/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
  
      if (!response.ok) {
        throw new Error(`Error: ${response.status}`);
      }
  
      const data: Result[] = await response.json();
      return data;
  
    } catch (error) {
      console.error("Failed to fetch documents:", error);
      throw error;
    }
  }
  
  export {
    getSearchResults
  }