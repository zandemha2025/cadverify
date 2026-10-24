import Link from "next/link";

/**
 * Said at sign-up (it-13): the Terms and Privacy, and plainly where account
 * details go whatever the privacy choices (ScaleCAD's customer list in Notion).
 */
export function SignupDataNote() {
  return (
    <>
      Creating an account accepts the <Link href="/terms">Terms</Link>. Your name, email and phone go to ScaleCAD’s customer
      list (Notion) for support and follow-up, whatever your privacy choices. <Link href="/privacy#collect">Privacy</Link> lists
      every service that gets data.
    </>
  );
}
