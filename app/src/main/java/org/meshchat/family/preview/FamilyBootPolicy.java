package org.meshchat.family.preview;
/** Platform boot policy without Android dependencies, also exercised on the host. */
public final class FamilyBootPolicy {
 private FamilyBootPolicy(){}
 public static boolean messaging(boolean setup,boolean tcp,boolean radio,boolean mesh){return setup&&(tcp||radio||mesh);}
 public static boolean callsAllowed(int sdk,boolean boot){return !boot||sdk<35;}
}
