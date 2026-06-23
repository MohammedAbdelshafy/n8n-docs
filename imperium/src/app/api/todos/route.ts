import { withSupabase } from "@supabase/server";

export const GET = withSupabase({ auth: "user" }, async (_req, ctx) => {
  const { data, error } = await ctx.supabase.from("todos").select();
  if (error) return Response.json({ error: error.message }, { status: 500 });
  return Response.json(data);
});

export const POST = withSupabase({ auth: "user" }, async (req, ctx) => {
  const body = await req.json();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { data, error } = await (ctx.supabase as any)
    .from("todos")
    .insert({ name: body.name as string })
    .select()
    .single();
  if (error) return Response.json({ error: error.message }, { status: 500 });
  return Response.json(data, { status: 201 });
});
