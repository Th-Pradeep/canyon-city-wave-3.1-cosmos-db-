import DOMPurify from "dompurify";

type ParsedSupportingContentItem = {
    title: string;
    content: string;
};

export function parseSupportingContentItem(item: string): ParsedSupportingContentItem {
    // Assumes the item starts with the file name followed by : and the content.
    // Example: "sdp_corporate.pdf: this is the content that follows".
    const parts = item.split(": ");
    let title = parts[0];
    const content = DOMPurify.sanitize(parts.slice(1).join(": "));

    // Remove version pattern from PDF filenames (e.g., "Help Manual_v3.26.pdf" -> "Help Manual.pdf")
    title = title.replace(/_v[\d.]+\.pdf/i, '.pdf');

    return {
        title,
        content
    };
}
